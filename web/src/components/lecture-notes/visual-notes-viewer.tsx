"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { CircleAlertIcon, PencilIcon, UploadIcon } from "lucide-react";

import { clearDraft } from "@/components/lecture-notes/editor/draft";
import { useLectureNotes } from "@/components/lecture-notes/use-lecture-notes";
import { Alert, AlertAction, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import { buttonVariants } from "@/components/ui/button";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";
import {
  editNotesPath,
  getCourseInfo,
  lectureNotesSiteUrl,
  visualNotesPath,
  type LectureNotesRun,
} from "@/lib/api";

type VisualNotesViewerProps = {
  course: string;
  sessionId: string;
  /** A save being rendered: shown until it is published, then the notes it made. */
  runId?: string;
};

/** A lecture's notes, the newest published ones, in a sandboxed frame. */
export function VisualNotesViewer({
  course,
  sessionId,
  runId,
}: VisualNotesViewerProps) {
  const router = useRouter();
  const { published, runs, error } = useLectureNotes(course, sessionId);
  // A save that is still rendering, or failed to.
  const pending =
    (runId && runs?.find((r) => r.id === runId && r.status !== "succeeded")) || null;
  const run = pending ? null : (published[0] ?? null);

  // Once the save is published, the notes' own address shows it.
  useEffect(() => {
    if (runId && runs?.some((r) => r.id === runId && r.status === "succeeded")) {
      router.replace(visualNotesPath(course, sessionId));
    }
  }, [runId, runs, router, course, sessionId]);

  // Once an edit is published, the editor's draft of it is done with.
  useEffect(() => {
    if (run?.kind === "edit" && run.edited_from) clearDraft(run.edited_from);
  }, [run]);
  // undefined while loading, null when it couldn't be loaded.
  const [courseName, setCourseName] = useState<string | null>();

  useEffect(() => {
    getCourseInfo(course).then(
      (info) => setCourseName(info.name),
      () => setCourseName(null),
    );
  }, [course]);

  return (
    <VisualNotesFrame
      course={course}
      courseName={courseName}
      loading={runs === null && !error}
      toolbarLoading={courseName === undefined}
      run={run}
      pending={pending}
      error={error}
    />
  );
}

type VisualNotesFrameProps = {
  course: string;
  /** Shown in the breadcrumb; "Course" when it couldn't be loaded. */
  courseName: string | null | undefined;
  /** The runs are loading: a spinner in the frame, skeletons in the toolbar. */
  loading: boolean;
  /** Something else the toolbar shows (the course name) is still loading. */
  toolbarLoading?: boolean;
  run: LectureNotesRun | null;
  /** An edit being rendered (or that failed), shown instead of a page. */
  pending?: LectureNotesRun | null;
  error: string | null;
  /** Where a run's files are served; the API by default. */
  siteUrl?: (runId: string, file?: string) => string;
};

/** The notes page itself: a brand-coloured frame around a rounded box with the toolbar on top
 * and the notes in a sandboxed iframe below. */
export function VisualNotesFrame({
  course,
  courseName,
  loading,
  toolbarLoading = false,
  run,
  pending = null,
  error,
  siteUrl = lectureNotesSiteUrl,
}: VisualNotesFrameProps) {
  return (
    // Exactly fills the window under the app bar (h-16 plus its 1px border), so the page itself
    // never scrolls; only the notes do. The 1px pull-up lets the toolbar cover that border.
    <main className="-mt-px flex h-[calc(100svh-4rem)] min-h-96 flex-col">
      {/* The toolbar reads as the app bar's second row, in the same column, so its items line up
          with the logo and the avatar. */}
      <div className="relative bg-background">
        <div className="mx-auto flex w-full max-w-6xl flex-wrap items-center gap-3 px-4 py-2 sm:px-6">
          {loading || toolbarLoading ? (
            <>
              <Skeleton className="h-5 w-72 max-w-full" />
              <div className="flex-1" />
              <Skeleton className="h-8 w-22 rounded-full" />
            </>
          ) : (
            <>
              <Breadcrumb className="min-w-0 flex-1">
                <BreadcrumbList className="flex-nowrap font-medium">
                  <BreadcrumbItem className="min-w-0 shrink">
                    <BreadcrumbLink
                      className={cn(
                        buttonVariants({ variant: "ghost", size: "sm" }),
                        "-ml-2.5 min-w-0 shrink text-sm",
                      )}
                      render={
                        <Link href={`/courses/${encodeURIComponent(course)}`} />
                      }
                    >
                      <span className="truncate">{courseName ?? "Course"}</span>
                    </BreadcrumbLink>
                  </BreadcrumbItem>
                  <BreadcrumbSeparator />
                  <BreadcrumbItem className="min-w-0">
                    <BreadcrumbPage className="truncate font-medium">
                      {run?.session_label ?? "Notes"}
                    </BreadcrumbPage>
                  </BreadcrumbItem>
                </BreadcrumbList>
              </Breadcrumb>
              {run && (
                <Link
                  href={editNotesPath(course, run.session_id)}
                  className={buttonVariants({ variant: "outline" })}
                >
                  <PencilIcon data-icon="inline-start" />
                  Edit
                </Link>
              )}
              {run && (
                <a
                  href={siteUrl(run.id)}
                  target="_blank"
                  rel="noreferrer"
                  className={buttonVariants()}
                >
                  <UploadIcon data-icon="inline-start" />
                  Share
                </a>
              )}
            </>
          )}
        </div>
      </div>

      <div className="flex min-h-0 flex-1 flex-col bg-primary p-1.5 sm:p-2">
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl bg-background">
          {error && (
            <Alert variant="destructive" className="m-3 w-auto">
              <CircleAlertIcon />
              <AlertTitle>Couldn&apos;t load the notes</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          {loading && (
            <div className="flex flex-1 items-center justify-center">
              <Spinner className="size-6 text-muted-foreground" />
            </div>
          )}

          {!loading && pending?.status === "running" && (
            <Empty className="m-3 border border-dashed">
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <Spinner />
                </EmptyMedia>
                <EmptyTitle>Publishing your edits</EmptyTitle>
                <EmptyDescription>
                  The notes are being rendered; this takes up to a minute.
                </EmptyDescription>
              </EmptyHeader>
            </Empty>
          )}

          {!loading && pending && pending.status !== "running" && (
            <Alert variant="destructive" className="m-3 w-auto">
              <CircleAlertIcon />
              <AlertTitle>Your edits weren&apos;t published</AlertTitle>
              <AlertDescription>
                {pending.error ?? "The notes didn't render."} Your changes are kept in the editor.
              </AlertDescription>
              <AlertAction>
                <Link
                  href={editNotesPath(course, pending.session_id)}
                  className={buttonVariants({ variant: "outline", size: "sm" })}
                >
                  Back to the editor
                </Link>
              </AlertAction>
            </Alert>
          )}

          {!loading && !error && !run && !pending && (
            <Empty className="m-3 border border-dashed">
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <CircleAlertIcon />
                </EmptyMedia>
                <EmptyTitle>No notes to show</EmptyTitle>
                <EmptyDescription>
                  Create them on the lecture page; they appear here when they
                  are ready.
                </EmptyDescription>
              </EmptyHeader>
            </Empty>
          )}

          {run && (
            <iframe
              key={run.id}
              title={`Notes: ${run.session_label}`}
              src={siteUrl(run.id)}
              sandbox="allow-scripts allow-popups allow-popups-to-escape-sandbox"
              referrerPolicy="no-referrer"
              className="w-full flex-1 bg-background"
            />
          )}
        </div>
      </div>
    </main>
  );
}
