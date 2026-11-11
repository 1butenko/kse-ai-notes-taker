"use client";

import Link from "next/link";
import {
  CircleAlertIcon,
  CircleCheckIcon,
  CircleDashedIcon,
  CircleStopIcon,
  InfoIcon,
  PresentationIcon,
  SparklesIcon,
} from "lucide-react";

import { useLectureNotes } from "@/components/lecture-notes/use-lecture-notes";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Item, ItemContent, ItemGroup, ItemMedia, ItemTitle } from "@/components/ui/item";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { visualNotesPath, type AgentTodo, type LectureNotesRun } from "@/lib/api";

function when(iso: string) {
  return new Date(iso).toLocaleString(undefined, {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function TodoIcon({ status }: { status: AgentTodo["status"] }) {
  if (status === "completed") return <CircleCheckIcon />;
  if (status === "in_progress") return <Spinner />;
  return <CircleDashedIcon />;
}

/** What the agent is doing: its current step and its todo list. */
function RunActivity({ run }: { run: LectureNotesRun }) {
  return (
    <div className="flex flex-col gap-3">
      <p className="flex items-center gap-2 text-sm" aria-live="polite">
        <Spinner />
        {run.step ?? "Starting"}
      </p>
      {run.todos.length > 0 && (
        <ItemGroup className="gap-1">
          {run.todos.map((todo, index) => (
            <Item key={index} size="sm" variant="muted">
              <ItemMedia variant="icon">
                <TodoIcon status={todo.status} />
              </ItemMedia>
              <ItemContent>
                <ItemTitle className="font-normal">{todo.content}</ItemTitle>
              </ItemContent>
            </Item>
          ))}
        </ItemGroup>
      )}
    </div>
  );
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
        <CardDescription>
          A study page with diagrams, interactive figures, worked examples and self-checks,
          written by the AI from this lecture&apos;s readings.
        </CardDescription>
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

        {active && <RunActivity run={active} />}

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
            href={visualNotesPath(course, sessionId, current.id)}
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
