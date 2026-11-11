"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeftIcon, CircleAlertIcon } from "lucide-react";
import { toast } from "sonner";

import { LectureFilesDrop } from "@/components/course/lecture-files-drop";
import { PanelTitle } from "@/components/course/materials-panel";
import { AddMaterialDialog } from "@/components/dashboard/add-material-dialog";
import { FileRow } from "@/components/dashboard/course-plan";
import { FileViewerProvider } from "@/components/dashboard/file-viewer";
import { SessionProposals } from "@/components/dashboard/mapping-parts";
import { ReadingList } from "@/components/dashboard/transcript-parts";
import { VisualNotesSection } from "@/components/lecture-notes/visual-notes-section";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { ItemGroup } from "@/components/ui/item";
import { Skeleton } from "@/components/ui/skeleton";
import {
  ApiError,
  detachFile,
  getCourseInfo,
  getPlan,
  listCourseFiles,
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
  const cited = session.required_readings.length + session.optional_readings.length;

  return (
    <aside
      aria-label="Lecture materials"
      className="flex min-w-0 flex-col gap-4 rounded-xl bg-muted p-4 lg:sticky lg:top-4"
    >
      {session.subtopics.length > 0 && (
        <div className="flex flex-col gap-3 border-b pb-4">
          <PanelTitle id="topics-title" title="Topics" count={session.subtopics.length} />
          <ul aria-labelledby="topics-title" className="flex flex-col">
            {session.subtopics.map((subtopic, index) => (
              <li
                key={index}
                className="border-b border-border py-2 text-sm last:border-b-0 last:pb-0"
              >
                {subtopic}
              </li>
            ))}
          </ul>
        </div>
      )}

      {cited > 0 && (
        <div className="flex flex-col gap-3 border-b pb-4">
          <PanelTitle id="syllabus-readings-title" title="Syllabus" count={cited} />
          <ReadingList
            title="Required"
            readings={session.required_readings}
            materials={materials}
          />
          <ReadingList
            title="Optional"
            readings={session.optional_readings}
            materials={materials}
          />
        </div>
      )}

      <div className="flex flex-col gap-3 border-b pb-4">
        <PanelTitle id="readings-title" title="Readings" count={shared.length} />
        <p className="-mt-2 text-xs text-muted-foreground">
          Course readings the note is written from.
        </p>
        <SessionProposals proposals={entry.proposals} course={plan.course} update={update} />
        {shared.length > 0 ? (
          <ItemGroup aria-labelledby="readings-title" className="gap-2">
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

      <div className="flex flex-col gap-3">
        <PanelTitle id="own-files-title" title="This lecture only" count={own.length} />
        {own.length > 0 && (
          <ItemGroup aria-labelledby="own-files-title" className="gap-2">
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
    </aside>
  );
}

/** One lecture: its notes (or the way to write them) and the readings they are written from. */
export function LecturePage({ course, sessionId }: LecturePageProps) {
  const [plan, setPlan] = useState<PlanView | null>(null);
  const [readingFiles, setReadingFiles] = useState<SavedFile[]>([]);
  const [courseName, setCourseName] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

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
                Its notes stay in the app, but it no longer has a lecture page.
              </EmptyDescription>
            </EmptyHeader>
          </Empty>
        )}

        {plan && entry && (
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
            <div className="grid grid-cols-[minmax(0,1fr)] gap-10 lg:grid-cols-[minmax(0,1fr)_24rem] lg:items-start">
              <div className="flex flex-col gap-8">
                <VisualNotesSection
                  course={course}
                  sessionId={entry.id}
                  hasReadings={entry.files.length > 0}
                />
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
