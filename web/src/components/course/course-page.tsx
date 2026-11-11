"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  CircleAlertIcon,
  EllipsisIcon,
  InfoIcon,
  RefreshCwIcon,
  Trash2Icon,
  UploadIcon,
} from "lucide-react";
import { toast } from "sonner";

import { AgentConsole } from "@/components/course/agent-console";
import { AgentReport, useAgentCourse } from "@/components/course/agent-materials";
import { LectureList } from "@/components/course/lecture-list";
import { MaterialsPanel } from "@/components/course/materials-panel";
import { SetupReview } from "@/components/course/setup-review";
import { SyllabusUpload } from "@/components/dashboard/syllabus-upload";
import { useCourseLectureNotes } from "@/components/lecture-notes/use-course-lecture-notes";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { Switch } from "@/components/ui/switch";
import { useDeveloperMode } from "@/hooks/use-developer-mode";
import {
  ApiError,
  deleteCourse,
  deleteSyllabus,
  getCourseInfo,
  getPlan,
  listCourseFiles,
  startAgentSync,
  setPrimarySyllabus,
  transcribeSyllabus,
  uploadFiles,
  type CourseFiles,
  type CourseInfo,
  type PlanView,
} from "@/lib/api";

const TRANSCRIBABLE = /\.(pdf|docx)$/i;

type CoursePageProps = {
  course: string;
  name: string;
  onDeleted: () => void;
};

function errorMessage(err: unknown) {
  return err instanceof ApiError ? err.message : "Couldn't reach the server. Please try again.";
}

function plural(count: number, one: string, many: string) {
  return `${count} ${count === 1 ? one : many}`;
}


/** Reads the syllabus into lectures and makes it the course plan. */
async function readSyllabus(course: string, path: string, force: boolean) {
  await transcribeSyllabus(path, force);
  const plan = await getPlan(course);
  return plan.primary === path ? plan : setPrimarySyllabus(course, path);
}

function SetupProgress({ title, detail }: { title: string; detail: string }) {
  return (
    <section aria-busy="true" className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <h2 className="flex items-center gap-2 text-xl">
          <Spinner />
          {title}
        </h2>
        <p className="text-muted-foreground">{detail}</p>
      </div>
      <div className="flex flex-col gap-3 border-t pt-4">
        {Array.from({ length: 5 }, (_, index) => (
          <Skeleton key={index} className="h-10 w-full" />
        ))}
      </div>
    </section>
  );
}

export function CoursePage({ course, name, onDeleted }: CoursePageProps) {
  const courseId = /^\d+$/.test(course) ? Number(course) : undefined;
  const [developerMode, setDeveloperMode] = useDeveloperMode();
  const [files, setFiles] = useState<CourseFiles | null>(null);
  const [plan, setPlan] = useState<PlanView | null>(null);
  // undefined while loading; null for a course stored before course names existed.
  const [info, setInfo] = useState<CourseInfo | null | undefined>(undefined);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reading, setReading] = useState(false);
  const [readError, setReadError] = useState<string | null>(null);
  // Re-reading the syllabus sends the lecturer back to review, though the plan stays mapped.
  const [forceReview, setForceReview] = useState(false);
  // A syllabus without a reading list never gets book matches, so approval is remembered here.
  const [approvedHere, setApprovedHere] = useState(false);
  const [newSyllabus, setNewSyllabus] = useState<File[]>([]);
  const [replacing, setReplacing] = useState<"closed" | "open" | "saving">("closed");
  const [deleting, setDeleting] = useState<"closed" | "open" | "deleting">("closed");
  const notes = useCourseLectureNotes(course);
  const agent = useAgentCourse(course, courseId !== undefined);
  // A course the AI Note Taker sets up: it reads the syllabus and prepares the lectures.
  const agentRun = agent.data?.latest_run ?? undefined;
  const agentPrepared = agentRun?.status === "succeeded";

  const load = useCallback(
    () =>
      Promise.all([
        listCourseFiles(course),
        getPlan(course).catch(() => null),
        getCourseInfo(course).catch(() => null),
      ]).then(
        ([loadedFiles, loadedPlan, loadedInfo]) => {
          setFiles(loadedFiles);
          setPlan(loadedPlan);
          setInfo(loadedInfo);
          setLoadError(null);
        },
        (err) => setLoadError(errorMessage(err)),
      ),
    [course],
  );

  useEffect(() => {
    load();
  }, [load]);

  const reloadFiles = () => {
    listCourseFiles(course).then(setFiles, () => {});
  };

  // Reading the lectures anew clears the readings approval on the server too.
  const forgetReadingsApproval = () =>
    setInfo((prev) => (prev ? { ...prev, readings_approved_at: null } : prev));

  const syllabusPath =
    plan?.primary ??
    files?.syllabus.map((f) => f.path).find((path) => TRANSCRIBABLE.test(path)) ??
    null;

  const readingsApproved = Boolean(info?.readings_approved_at);
  const phase =
    files === null || info === undefined || (agent.data === undefined && !agent.loadError)
      ? "loading"
      : files.syllabus.length === 0
        ? "syllabus"
        : !plan?.transcript
          ? "reading"
          : // Approved readings imply approved lectures, also for a syllabus without a reading list.
            // The AI Note Taker prepared the lectures itself: nothing to check.
            forceReview || !(plan.mapped || approvedHere || readingsApproved || agentPrepared)
            ? "review"
            : "ready";
  // While the AI Note Taker sets the course up (or could not finish), its console replaces
  // the setup screens.
  const agentSetup =
    agentRun !== undefined &&
    phase !== "loading" &&
    phase !== "ready" &&
    (agent.working || phase === "syllabus" || phase === "reading");

  // Its work lands in the course's files and plan: load them once it stops.
  const wasWorking = useRef(agent.working);
  useEffect(() => {
    if (wasWorking.current && !agent.working) load();
    wasWorking.current = agent.working;
  }, [agent.working, load]);

  const [retrying, setRetrying] = useState(false);
  const retryAgent = async () => {
    setRetrying(true);
    try {
      await startAgentSync(course);
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setRetrying(false);
      agent.refresh();
    }
  };

  const read = async (path: string, force: boolean) => {
    setReading(true);
    setReadError(null);
    try {
      setPlan(await readSyllabus(course, path, force));
    } catch (err) {
      setReadError(errorMessage(err));
    } finally {
      setReading(false);
    }
  };

  // The syllabus is read as soon as it is stored; no button to press.
  // Not for an AI Note Taker course: the agent reads its syllabus.
  const autoRead = phase === "reading" && !readError && !agentRun ? syllabusPath : null;
  useEffect(() => {
    if (!autoRead) return;
    let cancelled = false;
    readSyllabus(course, autoRead, false).then(
      (next) => !cancelled && setPlan(next),
      (err) => !cancelled && setReadError(errorMessage(err)),
    );
    return () => {
      cancelled = true;
    };
  }, [course, autoRead]);

  const reread = async () => {
    if (!syllabusPath) return;
    setForceReview(true);
    forgetReadingsApproval();
    await read(syllabusPath, true);
  };

  const replaceSyllabus = async () => {
    const file = newSyllabus[0];
    if (!file) return;
    setReplacing("saving");
    try {
      const [saved] = await uploadFiles("syllabus", [file], courseId);
      for (const old of files?.syllabus ?? []) {
        if (old.path !== saved.path) await deleteSyllabus(old.path);
      }
      setNewSyllabus([]);
      setReplacing("closed");
      setForceReview(true);
        forgetReadingsApproval();
      reloadFiles();
      await read(saved.path, true);
    } catch (err) {
      toast.error(errorMessage(err));
      setReplacing("open");
    }
  };

  const startOver = async () => {
    setDeleting("deleting");
    try {
      await deleteCourse(course);
      onDeleted();
    } catch (err) {
      toast.error(errorMessage(err));
      setDeleting("open");
    }
  };

  const saveFirstSyllabus = async () => {
    if (newSyllabus.length === 0) return;
    setReplacing("saving");
    try {
      await uploadFiles("syllabus", newSyllabus, courseId);
      setNewSyllabus([]);
      await load();
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setReplacing("closed");
    }
  };

  const hasMaterials = Boolean(plan?.sessions.some((s) => s.files.length > 0));
  const lectures = plan?.transcript?.sessions.length ?? 0;

  return (
    <div className="flex flex-col gap-8">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex min-w-0 flex-col gap-1">
          <h1 className="text-3xl">{name}</h1>
          <p className="text-muted-foreground">
            {agentSetup
              ? "Setting up with the AI Note Taker"
              : phase === "ready"
              ? plural(lectures, "lecture", "lectures")
              : phase === "review"
                ? "Setting up: check the lectures"
                : "Setting up"}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <DropdownMenu>
            <DropdownMenuTrigger
              render={<Button variant="outline" size="icon-lg" aria-label="Course menu" />}
            >
              <EllipsisIcon />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="min-w-56">
              <DropdownMenuItem
                closeOnClick={false}
                onClick={() => setDeveloperMode(!developerMode)}
              >
                Developer mode
                <Switch
                  size="sm"
                  checked={developerMode}
                  tabIndex={-1}
                  aria-label="Developer mode"
                  className="pointer-events-none ml-auto"
                />
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem disabled={!syllabusPath || reading} onClick={reread}>
                <RefreshCwIcon />
                Read the syllabus again
              </DropdownMenuItem>
              <DropdownMenuItem disabled={reading} onClick={() => setReplacing("open")}>
                <UploadIcon />
                Replace the syllabus file
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem variant="destructive" onClick={() => setDeleting("open")}>
                <Trash2Icon />
                Start over
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </header>

      {loadError && (
        <Alert variant="destructive">
          <CircleAlertIcon />
          <AlertTitle>Couldn&apos;t load the course</AlertTitle>
          <AlertDescription className="flex flex-col items-start gap-2">
            {loadError}
            <Button size="sm" variant="outline" onClick={load}>
              Try again
            </Button>
          </AlertDescription>
        </Alert>
      )}

      {phase === "loading" && !loadError && (
        // Shown only when loading takes a moment, so a fresh course goes straight to the
        // agent's console without a flash of placeholders.
        <div className="flex flex-col gap-3 animate-in fade-in duration-500 delay-300 fill-mode-backwards">
          {Array.from({ length: 6 }, (_, index) => (
            <Skeleton key={index} className="h-14 w-full" />
          ))}
        </div>
      )}

      {agentSetup && agentRun && (
        <AgentConsole
          run={agentRun}
          onRetry={retryAgent}
          retrying={retrying}
          incomplete={phase === "syllabus" || phase === "reading"}
        />
      )}

      {!agentSetup && phase === "syllabus" && (
        <section className="flex max-w-xl flex-col gap-4">
          <p className="text-muted-foreground">
            This course has no syllabus yet. Add it, and it is read into lectures.
          </p>
          <SyllabusUpload
            files={newSyllabus}
            onFilesChange={setNewSyllabus}
            moodleFiles={[]}
            onRemoveMoodleFile={() => {}}
            savedFiles={[]}
          />
          <div>
            <Button disabled={newSyllabus.length === 0 || replacing === "saving"} onClick={saveFirstSyllabus}>
              {replacing === "saving" ? "Saving…" : "Save and read it"}
            </Button>
          </div>
        </section>
      )}

      {!agentSetup &&
        (phase === "reading" || (phase === "review" && (reading || readError))) &&
        (readError ? (
          <Alert variant="destructive">
            <CircleAlertIcon />
            <AlertTitle>Couldn&apos;t read the syllabus</AlertTitle>
            <AlertDescription className="flex flex-col items-start gap-2">
              {readError}
              <Button
                size="sm"
                variant="outline"
                onClick={() =>
                  phase === "reading"
                    ? setReadError(null)
                    : syllabusPath && read(syllabusPath, true)
                }
              >
                Try again
              </Button>
            </AlertDescription>
          </Alert>
        ) : (
          <SetupProgress
            title="Reading the syllabus…"
            detail="Finding its lectures, topics and readings. This usually takes up to a minute."
          />
        ))}

      {!agentSetup &&
        phase === "review" &&
        !reading &&
        !readError &&
        plan?.transcript &&
        syllabusPath && (
        <SetupReview
          // A fresh transcript starts a fresh review.
          key={plan.transcript.created_at}
          course={course}
          transcript={plan.transcript}
          syllabusPath={syllabusPath}
          onPlan={setPlan}
          onApproved={() => {
            setForceReview(false);
            setApprovedHere(true);
            forgetReadingsApproval();
          }}
        />
      )}

      {phase === "ready" && plan && files && (
        <>
          {!hasMaterials && (
            <Alert>
              <InfoIcon />
              <AlertTitle>No lecture has readings yet</AlertTitle>
              <AlertDescription>
                Add the books the syllabus cites, or drop a file on a lecture&apos;s page, to
                write its notes.
              </AlertDescription>
            </Alert>
          )}
          <div className="grid grid-cols-[minmax(0,1fr)] gap-8 lg:grid-cols-[minmax(0,1fr)_20rem] lg:items-start">
            <section aria-labelledby="notes-title" className="flex min-w-0 flex-col gap-3">
              <div className="flex flex-col gap-1">
                <h2 id="notes-title" className="text-xl">
                  Notes
                </h2>
              </div>
              <LectureList plan={plan} notes={notes} />
            </section>
            <MaterialsPanel
              plan={plan}
              courseId={courseId}
              syllabusFiles={files.syllabus}
              readingFiles={files.reading}
              onPlan={setPlan}
              onUploaded={reloadFiles}
            />
          </div>
        </>
      )}

      {developerMode && phase !== "loading" && !agentSetup && (
        <AgentReport agent={agent} />
      )}

      <Dialog
        open={replacing !== "closed" && phase !== "syllabus"}
        onOpenChange={(open) => replacing !== "saving" && setReplacing(open ? "open" : "closed")}
      >
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>Replace the syllabus file</DialogTitle>
            <DialogDescription>
              The new file is read into lectures for you to check again. Your edits to the current
              lectures are lost; readings attached to lectures that no longer exist move to
              Unassigned.
            </DialogDescription>
          </DialogHeader>
          <SyllabusUpload
            files={newSyllabus}
            onFilesChange={setNewSyllabus}
            moodleFiles={[]}
            onRemoveMoodleFile={() => {}}
            savedFiles={[]}
          />
          <DialogFooter>
            <DialogClose render={<Button type="button" variant="outline" />}>Cancel</DialogClose>
            <Button
              disabled={newSyllabus.length === 0 || replacing === "saving"}
              onClick={replaceSyllabus}
            >
              {replacing === "saving" ? "Replacing…" : "Replace and read"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={deleting !== "closed"}
        onOpenChange={(open) => deleting !== "deleting" && setDeleting(open ? "open" : "closed")}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Start over?</DialogTitle>
            <DialogDescription>
              {name} leaves the app with its syllabus, readings and lectures. The files move to
              the server&apos;s trash folder, where an administrator can restore them.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <DialogClose render={<Button type="button" variant="outline" />}>Cancel</DialogClose>
            <Button variant="destructive" disabled={deleting === "deleting"} onClick={startOver}>
              <Trash2Icon />
              {deleting === "deleting" ? "Deleting…" : "Delete the course"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

    </div>
  );
}
