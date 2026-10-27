"use client";

import { useCallback, useEffect, useState } from "react";
import {
  CircleAlertIcon,
  EllipsisIcon,
  HistoryIcon,
  InfoIcon,
  RefreshCwIcon,
  RotateCwIcon,
  SparklesIcon,
  Trash2Icon,
  UploadIcon,
} from "lucide-react";
import { toast } from "sonner";

import { LectureList } from "@/components/course/lecture-list";
import { MaterialsPanel } from "@/components/course/materials-panel";
import { SetupReview } from "@/components/course/setup-review";
import { useCourseNotes } from "@/components/course/use-course-notes";
import { NotesStage, RunProgress } from "@/components/dashboard/notes-stage";
import { SyllabusUpload } from "@/components/dashboard/syllabus-upload";
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
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import {
  ApiError,
  deleteCourse,
  deleteSyllabus,
  getPlan,
  listCourseFiles,
  setPrimarySyllabus,
  transcribeSyllabus,
  uploadFiles,
  type CourseFiles,
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
  const [files, setFiles] = useState<CourseFiles | null>(null);
  const [plan, setPlan] = useState<PlanView | null>(null);
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
  const [historyOpen, setHistoryOpen] = useState(false);
  const notes = useCourseNotes(course);

  const load = useCallback(
    () =>
      Promise.all([listCourseFiles(course), getPlan(course).catch(() => null)]).then(
        ([loadedFiles, loadedPlan]) => {
          setFiles(loadedFiles);
          setPlan(loadedPlan);
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

  const syllabusPath =
    plan?.primary ??
    files?.syllabus.map((f) => f.path).find((path) => TRANSCRIBABLE.test(path)) ??
    null;

  const phase =
    files === null
      ? "loading"
      : files.syllabus.length === 0
        ? "syllabus"
        : !plan?.transcript
          ? "reading"
          : forceReview || !(plan.mapped || approvedHere)
            ? "review"
            : "ready";

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
  const autoRead = phase === "reading" && !readError ? syllabusPath : null;
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
  const done = notes.done;
  const stale =
    phase === "ready" &&
    done?.run.materials &&
    plan?.materials &&
    done.run.materials !== plan.materials;
  const failed = notes.latest?.status === "failed" ? notes.latest : null;

  return (
    <div className="flex flex-col gap-8">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex min-w-0 flex-col gap-1">
          <h1 className="text-3xl">{name}</h1>
          <p className="text-muted-foreground">
            {phase === "ready"
              ? plural(lectures, "lecture", "lectures")
              : phase === "review"
                ? "Setting up: check the lectures"
                : "Setting up"}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {phase === "ready" && (
            <Button
              size="lg"
              disabled={!hasMaterials || notes.starting || notes.active !== null}
              onClick={() => notes.generate()}
            >
              {notes.starting || notes.active ? <Spinner /> : <SparklesIcon />}
              {notes.active ? "Generating…" : done ? "Generate again" : "Generate notes"}
            </Button>
          )}
          <DropdownMenu>
            <DropdownMenuTrigger
              render={<Button variant="outline" size="icon-lg" aria-label="Course menu" />}
            >
              <EllipsisIcon />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="min-w-56">
              <DropdownMenuItem
                disabled={!syllabusPath || reading}
                onClick={reread}
              >
                <RefreshCwIcon />
                Read the syllabus again
              </DropdownMenuItem>
              <DropdownMenuItem disabled={reading} onClick={() => setReplacing("open")}>
                <UploadIcon />
                Replace the syllabus file
              </DropdownMenuItem>
              <DropdownMenuItem disabled={phase !== "ready"} onClick={() => setHistoryOpen(true)}>
                <HistoryIcon />
                Previous generations
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                variant="destructive"
                disabled={notes.active !== null}
                onClick={() => setDeleting("open")}
              >
                <Trash2Icon />
                {notes.active ? "Start over (wait for the notes)" : "Start over"}
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
        <div className="flex flex-col gap-3">
          {Array.from({ length: 6 }, (_, index) => (
            <Skeleton key={index} className="h-14 w-full" />
          ))}
        </div>
      )}

      {phase === "syllabus" && (
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

      {(phase === "reading" || (phase === "review" && (reading || readError))) &&
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

      {phase === "review" && !reading && !readError && plan?.transcript && syllabusPath && (
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
          }}
        />
      )}

      {phase === "ready" && plan && files && (
        <>
          {notes.active && <RunProgress run={notes.active} />}
          {failed && !notes.active && (
            <Alert variant="destructive">
              <CircleAlertIcon />
              <AlertTitle>Generation failed</AlertTitle>
              <AlertDescription className="flex flex-col items-start gap-2">
                {failed.error}
                <Button
                  size="sm"
                  variant="outline"
                  disabled={notes.starting}
                  onClick={() => notes.generate(failed.id)}
                >
                  <RotateCwIcon />
                  Resume this run
                </Button>
              </AlertDescription>
            </Alert>
          )}
          {stale && (
            <Alert>
              <InfoIcon />
              <AlertTitle>Readings changed since these notes were generated</AlertTitle>
              <AlertDescription>Generate again to write the notes from the new readings.</AlertDescription>
            </Alert>
          )}
          {!hasMaterials && (
            <Alert>
              <InfoIcon />
              <AlertTitle>No lecture has readings yet</AlertTitle>
              <AlertDescription>
                Add the books the syllabus cites, or attach a file to a lecture, to generate notes.
              </AlertDescription>
            </Alert>
          )}
          <div className="grid grid-cols-[minmax(0,1fr)] gap-8 lg:grid-cols-[minmax(0,1fr)_20rem] lg:items-start">
            <LectureList
              plan={plan}
              courseId={courseId}
              readingFiles={files.reading}
              notes={done}
              onPlan={setPlan}
              onUploaded={reloadFiles}
            />
            <MaterialsPanel
              plan={plan}
              courseId={courseId}
              readingFiles={files.reading}
              onPlan={setPlan}
              onUploaded={reloadFiles}
            />
          </div>
        </>
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
              {name} leaves the app with its syllabus, readings, lectures and every generated note.
              The files move to the server&apos;s trash folder, where an administrator can restore
              them.
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

      <Sheet
        open={historyOpen}
        onOpenChange={(open) => {
          setHistoryOpen(open);
          if (!open) notes.reload();
        }}
      >
        <SheetContent className="w-full overflow-y-auto data-[side=right]:sm:max-w-2xl">
          <SheetHeader>
            <SheetTitle>Previous generations</SheetTitle>
          </SheetHeader>
          <div className="px-4 pb-4">
            <NotesStage course={course} hasMaterials={hasMaterials} onDoneChange={noop} />
          </div>
        </SheetContent>
      </Sheet>
    </div>
  );
}

function noop() {}
