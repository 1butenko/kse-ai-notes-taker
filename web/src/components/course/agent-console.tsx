"use client";

import { useEffect, useState } from "react";
import {
  BookMarkedIcon,
  BookOpenIcon,
  CheckIcon,
  ChevronDownIcon,
  CircleAlertIcon,
  GraduationCapIcon,
  LibraryIcon,
  LightbulbIcon,
  NotebookPenIcon,
  RotateCcwIcon,
  type LucideIcon,
} from "lucide-react";
import { cn } from "cn";

import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import type { AgentAction, AgentRun, AgentTodo } from "@/lib/api";

// The study icons the loader cycles through while the agent works.
const STUDY_ICONS: LucideIcon[] = [
  BookOpenIcon,
  NotebookPenIcon,
  LibraryIcon,
  LightbulbIcon,
  BookMarkedIcon,
  GraduationCapIcon,
];

// Actions that move files: they get a progress bar while they run.
const TRANSFER = /^(Downloading|Adding|Saving)/;

function useNow(active: boolean, ms: number) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(timer);
  }, [active, ms]);
  return now;
}

function elapsed(from: string, to: string | null, now: number) {
  const end = to ? Date.parse(to) : now;
  const seconds = Math.max(0, Math.round((end - Date.parse(from)) / 1000));
  return seconds < 60
    ? `${seconds}s`
    : `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

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

function ProgressBar() {
  return (
    <span className="relative block h-1 w-full overflow-hidden rounded-full bg-primary/15">
      <span className="absolute inset-y-0 left-0 w-2/5 rounded-full bg-primary motion-safe:animate-indeterminate motion-reduce:w-full motion-reduce:opacity-40" />
    </span>
  );
}

type StepState = "done" | "active" | "failed" | "pending";

function todoState(todo: AgentTodo, run: AgentRun): StepState {
  if (todo.status === "completed") return "done";
  if (todo.status === "in_progress")
    return run.status === "failed" ? "failed" : "active";
  return "pending";
}

/** One general step: a marker on a rail, its name, and under the active one what the agent
 * is doing right now. */
function Step({
  todo,
  state,
  last,
  current,
}: {
  todo: AgentTodo;
  state: StepState;
  last: boolean;
  current: AgentAction | undefined;
}) {
  return (
    <li className="relative flex gap-4 pb-6 last:pb-0">
      {!last && (
        <span
          aria-hidden
          className={cn(
            "absolute top-8 bottom-1 left-[0.9375rem] w-px transition-colors duration-700",
            state === "done" ? "bg-success/60" : "bg-border",
          )}
        />
      )}
      <span
        aria-hidden
        className={cn(
          "relative flex size-8 shrink-0 items-center justify-center rounded-full border transition-all duration-500",
          state === "done" && "border-success bg-success text-white",
          state === "active" && "border-primary bg-primary/10 text-primary",
          state === "failed" &&
            "border-destructive bg-destructive/10 text-destructive",
          state === "pending" && "bg-background text-muted-foreground",
        )}
      >
        {state === "done" ? (
          <CheckIcon className="size-4 animate-in zoom-in-50 duration-300" />
        ) : state === "failed" ? (
          <CircleAlertIcon className="size-4" />
        ) : state === "active" ? (
          <span className="size-2 rounded-full bg-primary motion-safe:animate-pulse" />
        ) : (
          <span className="size-1.5 rounded-full bg-muted-foreground/40" />
        )}
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-1.5 pt-1">
        <span
          className={cn(
            "transition-colors duration-500",
            state === "pending" && "text-muted-foreground",
            state === "active" && "font-medium",
            state === "done" && "text-muted-foreground",
          )}
        >
          {todo.content}
        </span>
        {state === "active" && current && (
          <div
            key={current.text}
            className="flex flex-col gap-2 animate-in fade-in slide-in-from-top-1 duration-500"
          >
            <span className="text-sm text-muted-foreground">
              {current.text}…
            </span>
            {TRANSFER.test(current.text) && <ProgressBar />}
          </div>
        )}
      </div>
    </li>
  );
}

function LogLine({ action }: { action: AgentAction }) {
  return (
    <li className="flex flex-col animate-in fade-in slide-in-from-top-1 duration-300">
      <span className="flex gap-2">
        <span
          aria-hidden
          className={cn(
            "shrink-0",
            action.status === "done" && "text-success",
            action.status === "failed" && "text-destructive",
            action.status === "running" &&
              "text-primary motion-safe:animate-pulse",
          )}
        >
          ●
        </span>
        <span>{action.text}</span>
      </span>
      {action.detail && (
        <span
          className={cn(
            "flex gap-2 pl-1 text-muted-foreground",
            action.status === "failed" && "text-destructive",
          )}
        >
          <span aria-hidden className="shrink-0">
            └
          </span>
          <span className="break-words">{action.detail}</span>
        </span>
      )}
    </li>
  );
}

/** The detailed log, folded away behind a chevron. */
function Details({ actions }: { actions: AgentAction[] }) {
  const [open, setOpen] = useState(false);
  const failed = actions.filter((a) => a.status === "failed").length;
  return (
    <div className="flex flex-col border-t pt-4">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="flex items-center gap-2 self-start rounded-md text-sm text-muted-foreground transition-colors hover:text-foreground"
      >
        <ChevronDownIcon
          className={cn(
            "size-4 transition-transform duration-300",
            open && "rotate-180",
          )}
        />
        {open ? "Hide details" : "Show details"}
        <span className="tabular-nums">
          · {actions.length} {actions.length === 1 ? "action" : "actions"}
          {failed > 0 && (
            <span className="text-destructive">, {failed} failed</span>
          )}
        </span>
      </button>
      {/* Grid rows animate the height from 0 to the log's own. */}
      <div
        className={cn(
          "grid transition-[grid-template-rows,opacity] duration-500 ease-out",
          open ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0",
        )}
      >
        <div className="overflow-hidden">
          <ol className="mt-3 flex max-h-[40svh] flex-col gap-1.5 overflow-y-auto rounded-lg bg-muted/60 p-4 font-mono text-xs">
            {actions.map((action, index) => (
              <LogLine key={index} action={action} />
            ))}
          </ol>
        </div>
      </div>
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
 * The AI Note Taker at work, filling the page: a study-icon loader, what it is doing now, its
 * general steps, and the detailed log behind a chevron.
 */
export function AgentConsole({
  run,
  onRetry,
  retrying,
  incomplete,
}: AgentConsoleProps) {
  const working = run.status === "running";
  const now = useNow(working, 1000);

  // Before the agent writes its todo list, planning is the one step there is.
  const todos: AgentTodo[] =
    run.todos.length > 0
      ? run.todos
      : [
          {
            content: "Planning the work",
            status: working ? "in_progress" : "completed",
          },
        ];
  const current = [...run.actions]
    .reverse()
    .find((a) => a.status === "running");
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
            AI Note Taker · {elapsed(run.started_at, run.finished_at, now)}
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

        <ol className="w-full max-w-md" aria-label="Steps">
          {todos.map((todo, index) => (
            <Step
              key={todo.content}
              todo={todo}
              state={todoState(todo, run)}
              last={index === todos.length - 1}
              current={current}
            />
          ))}
        </ol>

        {!working && onRetry && (run.status === "failed" || incomplete) && (
          <Button variant="outline" disabled={retrying} onClick={onRetry}>
            {retrying ? <Spinner /> : <RotateCcwIcon />}
            Run the AI Note Taker again
          </Button>
        )}
      </div>

      {run.actions.length > 0 && <Details actions={run.actions} />}
    </section>
  );
}
