"use client";

import {
  BookMarkedIcon,
  BookOpenIcon,
  CheckIcon,
  CircleAlertIcon,
  GraduationCapIcon,
  LibraryIcon,
  LightbulbIcon,
  NotebookPenIcon,
  RotateCcwIcon,
  type LucideIcon,
} from "lucide-react";
import { cn } from "cn";

import { AgentTrace, runTodos, useNow } from "@/components/agent/agent-trace";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import type { AgentRun } from "@/lib/api";

// The study icons the loader cycles through while the agent works.
const STUDY_ICONS: LucideIcon[] = [
  BookOpenIcon,
  NotebookPenIcon,
  LibraryIcon,
  LightbulbIcon,
  BookMarkedIcon,
  GraduationCapIcon,
];

/** Study icons cross-fading into each other while the agent works. */
function StudyLoader({ run }: { run: AgentRun }) {
  const working = run.status === "running";
  const now = useNow(working, 1800);
  const active = Math.floor(now / 1800) % STUDY_ICONS.length;

  return (
    <div
      aria-hidden
      className={cn(
        "relative flex size-16 items-center justify-center rounded-2xl transition-colors duration-700",
        working && "bg-primary/10 text-primary",
        run.status === "succeeded" && "bg-success/10 text-success",
        run.status === "failed" && "bg-destructive/10 text-destructive",
      )}
    >
      {working ? (
        STUDY_ICONS.map((Icon, index) => (
          <Icon
            key={index}
            className={cn(
              "absolute size-7 transition-all duration-700 ease-out motion-reduce:transition-none",
              index === active ? "scale-100 opacity-100" : "scale-75 opacity-0",
            )}
          />
        ))
      ) : run.status === "failed" ? (
        <CircleAlertIcon className="size-7 animate-in zoom-in-50 fade-in duration-500" />
      ) : (
        <CheckIcon className="size-7 animate-in zoom-in-50 fade-in duration-500" />
      )}
    </div>
  );
}

type AgentConsoleProps = {
  run: AgentRun;
  /** Starts the agent again after a failed or unfinished run. */
  onRetry?: () => void;
  retrying?: boolean;
  /** The run ended without the syllabus read into lectures. */
  incomplete?: boolean;
};

/**
 * The AI Note Taker at work, filling the page: a study-icon loader, what it is doing now, and
 * its run as a Trace (steps, then every action behind one line).
 */
export function AgentConsole({
  run,
  onRetry,
  retrying,
  incomplete,
}: AgentConsoleProps) {
  const working = run.status === "running";
  const todos = runTodos(run);
  const done = todos.filter((t) => t.status === "completed").length;
  const position = Math.min(done + 1, todos.length);

  const headline = working
    ? (run.step ?? "Getting started")
    : run.status === "failed"
      ? "The AI Note Taker stopped"
      : incomplete
        ? "The AI Note Taker couldn't read the lectures"
        : "The course is ready to check";

  return (
    <section
      aria-label="The AI Note Taker"
      className="flex min-h-[calc(100svh-12rem)] w-full flex-col gap-8 rounded-2xl border bg-card p-6 shadow-sm animate-in fade-in zoom-in-[0.98] duration-500 sm:p-10"
    >
      <div className="flex flex-1 flex-col items-center justify-center gap-10">
        <div className="flex flex-col items-center gap-4 text-center">
          <StudyLoader run={run} />
          <p className="text-sm text-muted-foreground tabular-nums">
            AI Note Taker
            {working && ` · step ${position} of ${todos.length}`}
          </p>
          <h2
            key={headline}
            aria-live="polite"
            className="max-w-xl text-2xl text-balance animate-in fade-in slide-in-from-bottom-2 duration-500"
          >
            {headline}
            {working && "…"}
          </h2>
          {run.status === "failed" && run.error && (
            <p className="max-w-xl text-sm break-words text-destructive">
              {run.error}
            </p>
          )}
        </div>

        <div className="w-full max-w-md">
          <AgentTrace run={run} />
        </div>

        {!working && onRetry && (run.status === "failed" || incomplete) && (
          <Button variant="outline" disabled={retrying} onClick={onRetry}>
            {retrying ? <Spinner /> : <RotateCcwIcon />}
            Run the AI Note Taker again
          </Button>
        )}
      </div>
    </section>
  );
}
