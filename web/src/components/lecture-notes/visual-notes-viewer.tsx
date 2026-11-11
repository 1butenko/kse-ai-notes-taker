"use client";

import { useRouter } from "next/navigation";
import Link from "next/link";
import { ArrowLeftIcon, CircleAlertIcon, DownloadIcon, ExternalLinkIcon } from "lucide-react";

import { useLectureNotes } from "@/components/lecture-notes/use-lecture-notes";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { buttonVariants } from "@/components/ui/button";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { lecturePath, lectureNotesSiteUrl, visualNotesPath } from "@/lib/api";

function when(iso: string) {
  return new Date(iso).toLocaleString(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

type VisualNotesViewerProps = {
  course: string;
  sessionId: string;
  /** The run to show; the newest published one when missing. */
  runId?: string;
};

/** A published visual-notes page in a sandboxed frame, with its earlier versions. */
export function VisualNotesViewer({ course, sessionId, runId }: VisualNotesViewerProps) {
  const router = useRouter();
  const { published, runs, error } = useLectureNotes(course, sessionId);
  const run = (runId ? published.find((r) => r.id === runId) : published[0]) ?? null;

  return (
    <div className="flex min-h-[calc(100svh-6rem)] flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <Link
          href={lecturePath(course, sessionId)}
          className={buttonVariants({ variant: "ghost", size: "sm" })}
        >
          <ArrowLeftIcon data-icon="inline-start" />
          Lecture
        </Link>
        <h1 className="min-w-0 flex-1 truncate text-xl">{run?.session_label ?? "Notes"}</h1>
        {published.length > 1 && run && (
          <Select
            value={run.id}
            onValueChange={(value) =>
              value && router.push(visualNotesPath(course, sessionId, String(value)))
            }
            items={published.map((r) => ({
              value: r.id,
              label: when(r.finished_at ?? r.started_at),
            }))}
          >
            <SelectTrigger className="w-full sm:w-56" aria-label="Version">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                {published.map((r) => (
                  <SelectItem key={r.id} value={r.id}>
                    {when(r.finished_at ?? r.started_at)}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        )}
        {run && (
          <>
            <a
              href={lectureNotesSiteUrl(run.id)}
              target="_blank"
              rel="noreferrer"
              className={buttonVariants({ variant: "outline", size: "sm" })}
            >
              <ExternalLinkIcon data-icon="inline-start" />
              New tab
            </a>
            {run.files.includes("index.qmd") && (
              <a
                href={lectureNotesSiteUrl(run.id, "index.qmd")}
                className={buttonVariants({ variant: "outline", size: "sm" })}
              >
                <DownloadIcon data-icon="inline-start" />
                .qmd
              </a>
            )}
          </>
        )}
      </div>

      {error && (
        <Alert variant="destructive">
          <CircleAlertIcon />
          <AlertTitle>Couldn&apos;t load the notes</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {runs === null && !error && <Skeleton className="w-full flex-1" />}

      {runs !== null && !run && (
        <Empty className="border border-dashed">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <CircleAlertIcon />
            </EmptyMedia>
            <EmptyTitle>No notes to show</EmptyTitle>
            <EmptyDescription>
              Create them on the lecture page; they appear here when they are ready.
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      )}

      {run && (
        <iframe
          key={run.id}
          title={`Notes: ${run.session_label}`}
          src={lectureNotesSiteUrl(run.id)}
          sandbox="allow-scripts allow-popups allow-popups-to-escape-sandbox"
          referrerPolicy="no-referrer"
          className="w-full flex-1 rounded-lg border bg-background"
        />
      )}
    </div>
  );
}
