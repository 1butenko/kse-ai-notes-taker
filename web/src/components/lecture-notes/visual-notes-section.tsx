"use client";

import Link from "next/link";
import {
  CircleAlertIcon,
  CircleStopIcon,
  InfoIcon,
  PresentationIcon,
  SparklesIcon,
} from "lucide-react";

import { AgentTrace } from "@/components/agent/agent-trace";
import { useLectureNotes } from "@/components/lecture-notes/use-lecture-notes";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { visualNotesPath } from "@/lib/api";

function when(iso: string) {
  return new Date(iso).toLocaleString(undefined, {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

type VisualNotesSectionProps = {
  course: string;
  sessionId: string;
  hasReadings: boolean;
};

/** The lecture's visual notes: a Quarto page with diagrams and interactive figures, written by
 * the lecture-notes agent from the lecture's readings. */
export function VisualNotesSection({ course, sessionId, hasReadings }: VisualNotesSectionProps) {
  const notes = useLectureNotes(course, sessionId);
  const { active, latest, published, starting } = notes;
  const current = published[0] ?? null;
  const finishedBadly =
    latest && !active && (latest.status === "failed" || latest.status === "cancelled")
      ? latest
      : null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <PresentationIcon aria-hidden="true" />
          Notes
        </CardTitle>
        {current && (
          <CardAction>
            <Badge variant={current.readings_changed ? "outline" : "secondary"}>
              {current.readings_changed ? "Readings changed" : "Ready"}
            </Badge>
          </CardAction>
        )}
      </CardHeader>

      <CardContent className="flex flex-col gap-4">
        {notes.runs === null && !notes.error && <Skeleton className="h-16 w-full" />}

        {notes.error && (
          <Alert variant="destructive">
            <CircleAlertIcon />
            <AlertTitle>Couldn&apos;t load the notes</AlertTitle>
            <AlertDescription>{notes.error}</AlertDescription>
          </Alert>
        )}

        {active && <AgentTrace run={active} />}

        {finishedBadly && (
          <Alert variant={finishedBadly.status === "cancelled" ? "default" : "destructive"}>
            {finishedBadly.status === "cancelled" ? <InfoIcon /> : <CircleAlertIcon />}
            <AlertTitle>
              {finishedBadly.status === "cancelled" ? "Stopped" : "Writing the notes failed"}
            </AlertTitle>
            <AlertDescription>
              {finishedBadly.error ?? "The run ended without a page."}
              {current && " The previous page is still available."}
            </AlertDescription>
          </Alert>
        )}

        {/* Where the failed or stopped run got to. */}
        {finishedBadly && <AgentTrace run={finishedBadly} />}

        {current && !active && (
          <p className="text-sm text-muted-foreground">
            Written {when(current.finished_at ?? current.started_at)}
            {current.readings_changed &&
              ". The readings changed since then; write the notes again to include them"}
            .
          </p>
        )}

        {!active && !current && !finishedBadly && notes.runs !== null && (
          <p className="text-sm text-muted-foreground">
            {hasReadings
              ? "No notes yet. Writing them takes a few minutes; you can close this tab meanwhile."
              : "Add readings to this lecture first."}
          </p>
        )}
      </CardContent>

      <CardFooter className="flex flex-wrap gap-2">
        {current && (
          <Link
            href={visualNotesPath(course, sessionId)}
            className={buttonVariants()}
          >
            <PresentationIcon data-icon="inline-start" />
            Open notes
          </Link>
        )}
        {active ? (
          <Button variant="outline" disabled={starting} onClick={notes.cancel}>
            {starting ? <Spinner data-icon="inline-start" /> : <CircleStopIcon data-icon="inline-start" />}
            Stop
          </Button>
        ) : (
          <Button
            variant={current ? "outline" : "default"}
            disabled={!hasReadings || starting || notes.runs === null}
            onClick={notes.start}
          >
            {starting ? <Spinner data-icon="inline-start" /> : <SparklesIcon data-icon="inline-start" />}
            {current ? "Write again" : "Write the notes"}
          </Button>
        )}
      </CardFooter>
    </Card>
  );
}
