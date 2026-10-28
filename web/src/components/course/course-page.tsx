"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  BookOpenTextIcon,
  CircleAlertIcon,
  CircleStopIcon,
  EllipsisIcon,
  HistoryIcon,
  InfoIcon,
  RefreshCwIcon,
  SigmaIcon,
  SparklesIcon,
  Trash2Icon,
  UploadIcon,
} from "lucide-react";
import { toast } from "sonner";

import { LectureList } from "@/components/course/lecture-list";
import { MaterialsPanel } from "@/components/course/materials-panel";
import { ReadingsReview } from "@/components/course/readings-review";
import { SetupReview } from "@/components/course/setup-review";
import { useCourseNotes, type CourseNotes } from "@/components/course/use-course-notes";
import { RunProgress } from "@/components/dashboard/notes-stage";
import { SyllabusUpload } from "@/components/dashboard/syllabus-upload";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
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
  approveReadings,
  deleteCourse,
  deleteSyllabus,
  getCourseInfo,
  getCourseNotation,
  getPlan,
  listCourseFiles,
  previewPath,
  saveCourseInfo,
  setPrimarySyllabus,
  transcribeSyllabus,
  uploadFiles,
  type CourseFiles,
  type CourseInfo,
  type CourseNotation,
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

function when(iso: string) {
  return new Date(iso).toLocaleString(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
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

/** The run being written, which lecture it is, and how many wait after it. */
function QueueProgress({ plan, notes }: { plan: PlanView; notes: CourseNotes }) {
  const active = notes.active;
  const waiting = notes.queue.waiting.length;
  const lecture = active?.session_id
    ? plan.sessions.find((s) => s.id === active.session_id)
    : undefined;
  return (
    <section aria-label="Notes being written" className="flex flex-col gap-2">
      <p className="text-sm">
        {active
          ? lecture
            ? `Writing ${lecture.session.topic || lecture.session.label}`
            : "Writing whole-course notes"
          : "Starting the next lecture"}
        {waiting > 0 && `, ${plural(waiting, "lecture", "lectures")} queued after it`}
      </p>
      {active && <RunProgress run={active} />}
    </section>
  );
}

/** Whole-course generations from before lecture notes: still readable, never in the lectures. */
function PreviousGenerations({ course, notes }: { course: string; notes: CourseNotes }) {
  if (notes.legacy.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No whole-course generations. Each lecture&apos;s earlier notes are on its lecture page,
        under Previous versions.
      </p>
    );
  }
  return (
    <ul className="flex flex-col border-t">
      {notes.legacy.map((run) => (
        <li key={run.id} className="flex flex-wrap items-center gap-3 border-b py-3">
          <span className="flex min-w-0 flex-1 flex-col">
            <span className="font-medium">{when(run.created_at)}</span>
            <span className="text-sm text-muted-foreground">
              {run.status === "failed" ? run.error : "Whole-course notes"}
            </span>
          </span>
          <Badge variant={run.status === "failed" ? "destructive" : "outline"}>
            {run.status === "done" ? "Ready" : run.status === "failed" ? "Failed" : "Writing"}
          </Badge>
          {run.status === "done" && (
            <Link href={previewPath(course, run.id)} className={buttonVariants({ size: "sm" })}>
              Read notes
            </Link>
          )}
        </li>
      ))}
    </ul>
  );
}

function NotationTable({ notation }: { notation: CourseNotation | null }) {
  if (notation === null) return <Skeleton className="h-32 w-full" />;
  if (notation.notation.length === 0 && notation.terminology.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        Empty until the first lecture note is written. Its symbols and terms start the sheet, and
        every later lecture uses them and adds its own.
      </p>
    );
  }
  return (
    <div className="flex max-h-[60svh] flex-col gap-6 overflow-y-auto">
      {notation.notation.length > 0 && (
        <table className="w-full text-sm">
          <caption className="pb-2 text-left font-medium">Notation</caption>
          <tbody>
            {notation.notation.map((entry) => (
              <tr key={entry.symbol} className="border-t align-top">
                <th scope="row" className="w-1/3 py-2 pr-3 text-left font-normal tabular-nums">
                  {entry.symbol}
                </th>
                <td className="py-2 text-muted-foreground">{entry.meaning}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {notation.terminology.length > 0 && (
        <table className="w-full text-sm">
          <caption className="pb-2 text-left font-medium">Terms</caption>
          <tbody>
            {notation.terminology.map((entry) => (
              <tr key={entry.term} className="border-t align-top">
                <th scope="row" className="w-1/3 py-2 pr-3 text-left font-medium">
                  {entry.term}
                </th>
                <td className="py-2 text-muted-foreground">{entry.definition}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

export function CoursePage({ course, name, onDeleted }: CoursePageProps) {
  const courseId = /^\d+$/.test(course) ? Number(course) : undefined;
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
  // Readings per lecture, opened again from the course menu.
  const [showReadings, setShowReadings] = useState(false);
  const [newSyllabus, setNewSyllabus] = useState<File[]>([]);
  const [replacing, setReplacing] = useState<"closed" | "open" | "saving">("closed");
  const [deleting, setDeleting] = useState<"closed" | "open" | "deleting">("closed");
  const [historyOpen, setHistoryOpen] = useState(false);
  const [notationOpen, setNotationOpen] = useState(false);
  const [notation, setNotation] = useState<CourseNotation | null>(null);
  const notes = useCourseNotes(course);

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
    files === null || info === undefined
      ? "loading"
      : files.syllabus.length === 0
        ? "syllabus"
        : !plan?.transcript
          ? "reading"
          : // Approved readings imply approved lectures, also for a syllabus without a reading list.
            forceReview || !(plan.mapped || approvedHere || readingsApproved)
            ? "review"
            : showReadings || !readingsApproved
              ? "readings"
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
    setShowReadings(false);
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
      setShowReadings(false);
      forgetReadingsApproval();
      reloadFiles();
      await read(saved.path, true);
    } catch (err) {
      toast.error(errorMessage(err));
      setReplacing("open");
    }
  };

  const approve = async () => {
    try {
      setInfo(await approveReadings(course));
    } catch (err) {
      if (!(err instanceof ApiError && err.status === 404)) {
        toast.error(errorMessage(err));
        return;
      }
      // A course stored before course names existed gets its record first.
      try {
        await saveCourseInfo(course, name);
        setInfo(await approveReadings(course));
      } catch (again) {
        toast.error(errorMessage(again));
      }
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

  const openNotation = () => {
    setNotation(null);
    setNotationOpen(true);
    getCourseNotation(course).then(setNotation, (err) => {
      toast.error(errorMessage(err));
      setNotationOpen(false);
    });
  };

  const generateAll = async () => {
    const queued = await notes.generateAll();
    if (!queued) return;
    const count = queued.waiting.length + (queued.active ? 1 : 0);
    toast.success(`${plural(count, "lecture", "lectures")} queued`, {
      description:
        queued.skipped.length > 0
          ? `${plural(queued.skipped.length, "lecture was", "lectures were")} skipped: no readings.`
          : "They are written one at a time. You can close this tab.",
    });
  };

  const hasMaterials = Boolean(plan?.sessions.some((s) => s.files.length > 0));
  const lectures = plan?.transcript?.sessions.length ?? 0;
  const generating = notes.busy;

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
                : phase === "readings" && !readingsApproved
                  ? "Setting up: check the readings"
                  : "Setting up"}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {phase === "ready" &&
            (generating ? (
              <Button size="lg" variant="outline" disabled={notes.starting} onClick={notes.stop}>
                {notes.starting ? <Spinner /> : <CircleStopIcon />}
                Stop
              </Button>
            ) : (
              <Button
                size="lg"
                disabled={!hasMaterials || notes.starting || notes.loading}
                onClick={generateAll}
              >
                {notes.starting ? <Spinner /> : <SparklesIcon />}
                Generate all
              </Button>
            ))}
          <DropdownMenu>
            <DropdownMenuTrigger
              render={<Button variant="outline" size="icon-lg" aria-label="Course menu" />}
            >
              <EllipsisIcon />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="min-w-56">
              <DropdownMenuItem
                disabled={!readingsApproved || phase !== "ready"}
                onClick={() => setShowReadings(true)}
              >
                <BookOpenTextIcon />
                Readings per lecture
              </DropdownMenuItem>
              <DropdownMenuItem disabled={phase === "loading"} onClick={openNotation}>
                <SigmaIcon />
                Course notation
              </DropdownMenuItem>
              <DropdownMenuItem disabled={phase !== "ready"} onClick={() => setHistoryOpen(true)}>
                <HistoryIcon />
                Previous generations
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                disabled={!syllabusPath || reading || generating}
                onClick={reread}
              >
                <RefreshCwIcon />
                Read the syllabus again
              </DropdownMenuItem>
              <DropdownMenuItem
                disabled={reading || generating}
                onClick={() => setReplacing("open")}
              >
                <UploadIcon />
                Replace the syllabus file
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                variant="destructive"
                disabled={generating}
                onClick={() => setDeleting("open")}
              >
                <Trash2Icon />
                {generating ? "Start over (stop the notes first)" : "Start over"}
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
            forgetReadingsApproval();
          }}
        />
      )}

      {phase === "readings" && plan && files && (
        <ReadingsReview
          plan={plan}
          courseId={courseId}
          readingFiles={files.reading}
          onPlan={setPlan}
          onUploaded={reloadFiles}
          approved={readingsApproved}
          onApprove={approve}
          onClose={() => setShowReadings(false)}
        />
      )}

      {phase === "ready" && plan && files && (
        <>
          {generating && <QueueProgress plan={plan} notes={notes} />}
          {!hasMaterials && (
            <Alert>
              <InfoIcon />
              <AlertTitle>No lecture has readings yet</AlertTitle>
              <AlertDescription>
                Add the books the syllabus cites, or drop a file on a lecture&apos;s page, to
                generate its note.
              </AlertDescription>
            </Alert>
          )}
          <div className="grid grid-cols-[minmax(0,1fr)] gap-8 lg:grid-cols-[minmax(0,1fr)_20rem] lg:items-start">
            <section aria-labelledby="notes-title" className="flex min-w-0 flex-col gap-3">
              <div className="flex flex-col gap-1">
                <h2 id="notes-title" className="text-xl">
                  Notes
                </h2>
                <p className="text-sm text-muted-foreground">
                  One note per lecture, written when you ask for it. Open a lecture to write its
                  note or change its readings.
                </p>
              </div>
              <LectureList plan={plan} notes={notes} />
            </section>
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

      <Dialog open={notationOpen} onOpenChange={setNotationOpen}>
        <DialogContent className="sm:max-w-xl">
          <DialogHeader>
            <DialogTitle>Course notation</DialogTitle>
            <DialogDescription>
              The symbols and terms every lecture note uses. Each new note adds what it introduces;
              existing meanings never change.
            </DialogDescription>
          </DialogHeader>
          <NotationTable notation={notation} />
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
            <PreviousGenerations course={course} notes={notes} />
          </div>
        </SheetContent>
      </Sheet>
    </div>
  );
}
