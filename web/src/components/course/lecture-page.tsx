"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  ArrowLeftIcon,
  CircleAlertIcon,
  CircleStopIcon,
  FileTextIcon,
  InfoIcon,
  NotebookPenIcon,
  RotateCwIcon,
  SparklesIcon,
} from "lucide-react";
import { toast } from "sonner";

import { LectureFilesDrop } from "@/components/course/lecture-files-drop";
import { StatusBadge } from "@/components/course/lecture-list";
import {
  failedSections,
  noteStatus,
  readingsChanged,
  useCourseNotes,
  type LectureNotes,
} from "@/components/course/use-course-notes";
import { AddMaterialDialog } from "@/components/dashboard/add-material-dialog";
import { FileRow } from "@/components/dashboard/course-plan";
import { FileViewerProvider } from "@/components/dashboard/file-viewer";
import { SessionProposals } from "@/components/dashboard/mapping-parts";
import { RunProgress } from "@/components/dashboard/notes-stage";
import { ReadingList } from "@/components/dashboard/transcript-parts";
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
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { ItemGroup } from "@/components/ui/item";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import {
  ApiError,
  detachFile,
  getCourseInfo,
  getPlan,
  listCourseFiles,
  previewPath,
  type NotesRun,
  type PlanView,
  type SavedFile,
  type SessionView,
} from "@/lib/api";

type LecturePageProps = {
  course: string;
  sessionId: string;
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
    hour: "2-digit",
    minute: "2-digit",
  });
}

type NoteSectionProps = {
  course: string;
  entry: SessionView;
  lecture: LectureNotes;
  notes: ReturnType<typeof useCourseNotes>;
};

/** What the lecture's note is: missing, queued, being written, stopped, or ready. */
function NoteSection({ course, entry, lecture, notes }: NoteSectionProps) {
  const [confirming, setConfirming] = useState(false);
  const hasReadings = entry.files.length > 0;
  // One job per course: while another lecture is written, nothing else can start.
  const otherBusy = notes.busy && !lecture.active && !lecture.queued;
  const canStart = hasReadings && !notes.busy && !notes.starting;
  const blocked = !hasReadings
    ? "Add readings to this lecture first."
    : otherBusy
      ? "Another lecture is being written. Wait for it, or stop it from the course page."
      : null;
  const failed = failedSections(lecture);
  const { note, unfinished, active } = lecture;
  const stopped = unfinished?.error?.startsWith("Stopped") ?? false;

  const regenerate = async () => {
    setConfirming(false);
    await notes.generate(entry.id);
  };

  return (
    <section aria-labelledby="note-title" className="flex flex-col gap-4">
      <h2 id="note-title" className="text-xl">
        Note
      </h2>

      {active && (
        <div className="flex flex-col gap-3">
          <RunProgress run={active} />
          <div className="flex flex-wrap items-center gap-3">
            <Button variant="outline" disabled={notes.starting} onClick={notes.stop}>
              {notes.starting ? <Spinner /> : <CircleStopIcon />}
              Stop
            </Button>
            <p className="text-sm text-muted-foreground">
              {note
                ? "The current note stays readable until the new one is ready."
                : "You can close this tab; the note is written on the server."}{" "}
              Stop keeps the finished sections, and Resume writes the rest.
            </p>
          </div>
        </div>
      )}

      {lecture.queued && !active && (
        <Alert>
          <InfoIcon />
          <AlertTitle>Queued</AlertTitle>
          <AlertDescription className="flex flex-col items-start gap-2">
            This lecture is written after the ones queued before it.
            <Button size="sm" variant="outline" disabled={notes.starting} onClick={notes.stop}>
              <CircleStopIcon />
              Stop and clear the queue
            </Button>
          </AlertDescription>
        </Alert>
      )}

      {unfinished && !active && (
        <Alert variant={stopped ? "default" : "destructive"}>
          {stopped ? <InfoIcon /> : <CircleAlertIcon />}
          <AlertTitle>{stopped ? "Stopped" : "Writing the note failed"}</AlertTitle>
          <AlertDescription className="flex flex-col items-start gap-2">
            <span>
              {stopped ? "Stopped before the note was finished." : unfinished.error}{" "}
              {unfinished.topics_done > 0
                ? `${plural(unfinished.topics_done, "finished section is", "finished sections are")} kept; Resume writes the rest.`
                : "Resume continues where it stopped."}
            </span>
            <span className="flex flex-wrap gap-2">
              <Button
                size="sm"
                variant="outline"
                disabled={!canStart}
                onClick={() => notes.generate(entry.id, { resume: unfinished.id })}
              >
                <RotateCwIcon />
                Resume
              </Button>
              {!note && (
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={!canStart}
                  onClick={() => notes.generate(entry.id)}
                >
                  Start a new note
                </Button>
              )}
            </span>
          </AlertDescription>
        </Alert>
      )}

      {note ? (
        <div className="flex flex-col gap-3 rounded-lg border p-4">
          <div className="flex flex-wrap items-center gap-2">
            <FileTextIcon className="size-4 text-muted-foreground" aria-hidden="true" />
            <span className="font-medium">
              {lecture.view?.document?.title ?? entry.session.topic ?? entry.session.label}
            </span>
            <StatusBadge status={noteStatus(lecture)} lecture={lecture} />
            <span className="text-sm text-muted-foreground">Written {when(note.created_at)}</span>
          </div>
          {readingsChanged(lecture, entry) && (
            <p className="text-sm text-warning">
              Readings changed since this note was written. Regenerate to write it from the
              current readings.
            </p>
          )}
          {failed.length > 0 && (
            <p className="text-sm text-destructive">
              {plural(failed.length, "section", "sections")} failed:{" "}
              {failed.map((t) => t.title).join(", ")}.
            </p>
          )}
          <div className="flex flex-wrap gap-2">
            <Link href={previewPath(course, note.id)} className={buttonVariants()}>
              <FileTextIcon />
              Open note
            </Link>
            {failed.length > 0 && (
              <Button
                variant="outline"
                disabled={!canStart}
                onClick={() => notes.generate(entry.id, { retry: note.id })}
              >
                <RotateCwIcon />
                Retry failed section{failed.length === 1 ? "" : "s"}
              </Button>
            )}
            <Button variant="outline" disabled={!canStart} onClick={() => setConfirming(true)}>
              <SparklesIcon />
              Regenerate
            </Button>
          </div>
        </div>
      ) : (
        !active &&
        !lecture.queued &&
        !unfinished && (
          <Empty className="border border-dashed">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <NotebookPenIcon />
              </EmptyMedia>
              <EmptyTitle>This lecture has no note yet</EmptyTitle>
              <EmptyDescription>
                It is written from the readings below, in a few minutes. You can close the tab
                meanwhile.
              </EmptyDescription>
            </EmptyHeader>
            <EmptyContent>
              <Button disabled={!canStart} onClick={() => notes.generate(entry.id)}>
                {notes.starting ? <Spinner /> : <SparklesIcon />}
                Generate note
              </Button>
            </EmptyContent>
          </Empty>
        )
      )}

      {blocked && !active && !lecture.queued && (
        <p className="text-sm text-muted-foreground">{blocked}</p>
      )}

      <Dialog open={confirming} onOpenChange={setConfirming}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Regenerate this lecture&apos;s note?</DialogTitle>
            <DialogDescription>
              A new note is written from the current readings. The current one stays open until
              the new one is ready, then moves to Previous versions with its edits and approvals.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <DialogClose render={<Button type="button" variant="outline" />}>Cancel</DialogClose>
            <Button onClick={regenerate}>
              <SparklesIcon />
              Regenerate
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}

type ReadingsSectionProps = {
  plan: PlanView;
  entry: SessionView;
  readingFiles: SavedFile[];
  onPlan: (plan: PlanView) => void;
  onUploaded: () => void;
};

/** The lecture's readings: what the syllabus cites, the matched excerpts and attached files. */
function ReadingsSection({ plan, entry, readingFiles, onPlan, onUploaded }: ReadingsSectionProps) {
  const [busy, setBusy] = useState(false);
  const courseId = /^\d+$/.test(plan.course) ? Number(plan.course) : undefined;
  const update = async (action: () => Promise<PlanView>) => {
    if (busy) return;
    setBusy(true);
    try {
      onPlan(await action());
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  const { session } = entry;
  const materials = plan.transcript?.learning_materials ?? [];
  const shared = entry.files.filter((f) => !f.lecture_only);
  const own = entry.files.filter((f) => f.lecture_only);

  return (
    <section aria-labelledby="readings-title" className="flex flex-col gap-4">
      <h2 id="readings-title" className="text-xl">
        Readings
      </h2>
      {session.subtopics.length > 0 && (
        <ul className="list-disc pl-5 text-sm text-muted-foreground">
          {session.subtopics.map((subtopic, index) => (
            <li key={index}>{subtopic}</li>
          ))}
        </ul>
      )}
      <ReadingList
        title="Required in the syllabus"
        readings={session.required_readings}
        materials={materials}
      />
      <ReadingList
        title="Optional in the syllabus"
        readings={session.optional_readings}
        materials={materials}
      />
      <SessionProposals proposals={entry.proposals} course={plan.course} update={update} />
      <div className="flex flex-col gap-2">
        <span className="text-xs font-medium text-muted-foreground">
          Course readings the note is written from
        </span>
        {shared.length > 0 ? (
          <ItemGroup className="gap-2">
            {shared.map((file) => (
              <FileRow
                key={file.path}
                file={file}
                label="Detach"
                onRemove={() => update(() => detachFile(plan.course, entry.id, file.path))}
              />
            ))}
          </ItemGroup>
        ) : (
          <p className="text-sm text-muted-foreground">None yet.</p>
        )}
        <div>
          <AddMaterialDialog
            course={plan.course}
            courseId={courseId}
            entry={entry}
            readingFiles={readingFiles}
            onPlan={onPlan}
            onUploaded={onUploaded}
          />
        </div>
      </div>
      <div className="flex flex-col gap-2">
        <span className="text-xs font-medium text-muted-foreground">
          Files for this lecture only
        </span>
        {own.length > 0 && (
          <ItemGroup className="gap-2">
            {own.map((file) => (
              <FileRow
                key={file.path}
                file={file}
                label="Delete"
                onRemove={() => update(() => detachFile(plan.course, entry.id, file.path))}
              />
            ))}
          </ItemGroup>
        )}
        <LectureFilesDrop course={plan.course} sessionId={entry.id} onPlan={onPlan} />
      </div>
    </section>
  );
}

function PreviousVersions({ course, runs }: { course: string; runs: NotesRun[] }) {
  if (runs.length === 0) return null;
  return (
    <section aria-labelledby="versions-title" className="flex flex-col gap-2">
      <h2 id="versions-title" className="text-base">
        Previous versions
      </h2>
      <ul className="flex flex-col border-t">
        {runs.map((run) => (
          <li key={run.id} className="border-b">
            <Link
              href={previewPath(course, run.id)}
              className="flex min-h-11 items-center gap-3 px-2 py-2 transition-colors hover:bg-muted"
            >
              <FileTextIcon className="size-4 text-muted-foreground" aria-hidden="true" />
              <span className="flex-1">Written {when(run.created_at)}</span>
              {run.retried_from && <Badge variant="outline">Retry</Badge>}
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** One lecture: its note (or the way to write it) and the readings it is written from. */
export function LecturePage({ course, sessionId }: LecturePageProps) {
  const [plan, setPlan] = useState<PlanView | null>(null);
  const [readingFiles, setReadingFiles] = useState<SavedFile[]>([]);
  const [courseName, setCourseName] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const notes = useCourseNotes(course);

  const load = useCallback(
    () =>
      Promise.all([getPlan(course), listCourseFiles(course)]).then(
        ([loadedPlan, files]) => {
          setPlan(loadedPlan);
          setReadingFiles(files.reading);
          setLoadError(null);
        },
        (err) => setLoadError(errorMessage(err)),
      ),
    [course],
  );

  useEffect(() => {
    load();
    getCourseInfo(course).then(
      (info) => setCourseName(info.name),
      () => {},
    );
  }, [course, load]);

  const reloadFiles = () => {
    listCourseFiles(course).then((files) => setReadingFiles(files.reading), () => {});
  };

  const index = plan?.sessions.findIndex((s) => s.id === sessionId) ?? -1;
  const entry = plan && index >= 0 ? plan.sessions[index] : null;
  const lecture = entry ? notes.lecture(entry.id) : null;

  return (
    <FileViewerProvider>
      <div className="flex flex-col gap-8">
        <Link
          href="/"
          className="inline-flex items-center gap-1.5 self-start text-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
        >
          <ArrowLeftIcon className="size-4" aria-hidden="true" />
          {courseName ?? "Course"}: all lectures
        </Link>

        {loadError && (
          <Alert variant="destructive">
            <CircleAlertIcon />
            <AlertTitle>Couldn&apos;t load the lecture</AlertTitle>
            <AlertDescription className="flex flex-col items-start gap-2">
              {loadError}
              <Button size="sm" variant="outline" onClick={load}>
                Try again
              </Button>
            </AlertDescription>
          </Alert>
        )}

        {!plan && !loadError && (
          <div className="flex flex-col gap-4">
            <Skeleton className="h-9 w-80" />
            <Skeleton className="h-40 w-full" />
            <Skeleton className="h-64 w-full" />
          </div>
        )}

        {plan && !entry && (
          <Empty className="border border-dashed">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <CircleAlertIcon />
              </EmptyMedia>
              <EmptyTitle>This lecture is no longer in the syllabus</EmptyTitle>
              <EmptyDescription>
                Its earlier notes stay readable under Previous generations on the course page.
              </EmptyDescription>
            </EmptyHeader>
          </Empty>
        )}

        {plan && entry && lecture && (
          <>
            <header className="grid grid-cols-[3.5rem_minmax(0,1fr)] items-start gap-x-3">
              <span className="text-4xl leading-none font-bold tabular-nums">
                {entry.session.number ?? index + 1}
              </span>
              <div className="flex min-w-0 flex-col gap-1">
                <h1 className="text-3xl">{entry.session.topic || entry.session.label}</h1>
                <p className="text-muted-foreground">
                  {[entry.session.topic ? entry.session.label : null, entry.session.date]
                    .filter(Boolean)
                    .join(", ")}
                </p>
              </div>
            </header>
            <div className="grid grid-cols-[minmax(0,1fr)] gap-10 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] lg:items-start">
              <div className="flex flex-col gap-8">
                <NoteSection course={course} entry={entry} lecture={lecture} notes={notes} />
                <PreviousVersions course={course} runs={lecture.previous} />
              </div>
              <ReadingsSection
                plan={plan}
                entry={entry}
                readingFiles={readingFiles}
                onPlan={setPlan}
                onUploaded={reloadFiles}
              />
            </div>
          </>
        )}
      </div>
    </FileViewerProvider>
  );
}
