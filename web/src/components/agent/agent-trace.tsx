"use client";

import { useEffect, useState } from "react";
import {
  DownloadIcon,
  FilePlusIcon,
  FileTextIcon,
  GlobeIcon,
  PresentationIcon,
  SearchIcon,
  UploadIcon,
  WrenchIcon,
  type LucideIcon,
} from "lucide-react";

import {
  Trace,
  TraceCollapsible,
  TraceCollapsibleContent,
  TraceCollapsibleTrigger,
  TraceDescription,
  TraceIcon,
  TraceLine,
  TraceTitle,
} from "@/components/ui/trace";
import type { AgentAction, AgentTodo } from "@/lib/api";

/** What the trace needs from a course-agent run or a lecture-notes run. */
export type TracedRun = {
  status: "running" | "succeeded" | "failed" | "cancelled";
  step: string | null;
  todos: AgentTodo[];
  actions: AgentAction[];
  started_at: string;
  finished_at: string | null;
};

export function useNow(active: boolean, ms: number) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(timer);
  }, [active, ms]);
  return now;
}

/** Before the agent writes its todo list, its current step is the one there is. */
export function runTodos(run: TracedRun): AgentTodo[] {
  if (run.todos.length > 0) return run.todos;
  return [
    {
      content: run.step ?? "Planning the work",
      status: run.status === "running" ? "in_progress" : "completed",
    },
  ];
}

// The icon names the kind of action, as in shadcn's Trace; the line's status shows its state.
const ACTION_ICONS: [RegExp, LucideIcon][] = [
  [/^Downloading/, DownloadIcon],
  [/^Adding/, FilePlusIcon],
  [/^Saving the web page/, GlobeIcon],
  [/^(Finding|Looking|Matching|Searching)/, SearchIcon],
  [/^Rendering/, PresentationIcon],
  [/^Publishing/, UploadIcon],
  [/^Reading/, FileTextIcon],
];

function ActionIcon({ text }: { text: string }) {
  const Icon = ACTION_ICONS.find(([pattern]) => pattern.test(text))?.[1] ?? WrenchIcon;
  return (
    <TraceIcon>
      <Icon />
    </TraceIcon>
  );
}

function actionStatus(action: AgentAction) {
  if (action.status === "running") return "running";
  if (action.status === "failed") return "error";
  return undefined;
}

type StepGroup = {
  key: string;
  title: string;
  status: "running" | "error" | undefined;
  actions: AgentAction[];
  /** What the agent is doing between actions (reading, writing), shown in the running step. */
  doing?: string;
};

const FIRST_STEP = "Getting started";

/**
 * The steps the agent has reached, in plan order, each with the actions it took during it.
 * Steps it has not started are left out, so they appear one after another. An action whose step
 * is unknown (renamed, or an older run) joins the step of the action before it; the actions
 * before the plan form a first "Getting started" step.
 */
function stepGroups(run: TracedRun): StepGroup[] {
  const running = run.status === "running";
  const stopped = run.status === "failed" ? "error" : undefined;
  const reached = run.todos.filter((t) => t.status !== "pending");
  const byTodo = new Map<string, AgentAction[]>(reached.map((t) => [t.content, []]));
  const first: AgentAction[] = [];

  let previous: string | null = null;
  for (const action of run.actions) {
    const key: string | null = action.todo && byTodo.has(action.todo) ? action.todo : previous;
    (key === null ? first : byTodo.get(key)!).push(action);
    previous = key;
  }

  const groups: StepGroup[] = reached.map((todo) => ({
    key: todo.content,
    title: todo.content,
    status:
      todo.status === "in_progress" ? (running ? "running" : stopped) : undefined,
    actions: byTodo.get(todo.content)!,
  }));
  if (first.length > 0 || groups.length === 0) {
    groups.unshift({
      key: FIRST_STEP,
      title: FIRST_STEP,
      status: groups.length === 0 ? (running ? "running" : stopped) : undefined,
      actions: first,
    });
  }
  // Between actions the run's step is the agent's own activity, if it is not the step itself.
  const live = groups.find((g) => g.status === "running");
  if (live && run.step && run.step !== live.title && !run.actions.some((a) => a.status === "running")) {
    live.doing = run.step;
  }
  return groups;
}

/** One step: its title, and the actions it took inside, open while it runs or after it failed. */
function StepLine({ step }: { step: StepGroup }) {
  const [open, setOpen] = useState<boolean>();
  const failed = step.actions.filter((a) => a.status === "failed").length;
  const line = (
    <TraceLine status={step.status}>
      <TraceTitle>{step.title}</TraceTitle>
      {step.actions.length > 0 && (
        <TraceDescription>
          {step.actions.length} {step.actions.length === 1 ? "action" : "actions"}
          {failed > 0 && `, ${failed} failed`}
        </TraceDescription>
      )}
    </TraceLine>
  );
  if (step.actions.length === 0 && !step.doing) {
    return <div className="animate-in fade-in slide-in-from-top-1 duration-500">{line}</div>;
  }

  // The reader's click wins over the default.
  return (
    <TraceCollapsible
      open={open ?? step.status !== undefined}
      onOpenChange={setOpen}
      className="animate-in fade-in slide-in-from-top-1 duration-500"
    >
      <TraceCollapsibleTrigger>{line}</TraceCollapsibleTrigger>
      <TraceCollapsibleContent keepMounted>
        <Trace>
          {step.actions.map((action, index) => (
            <ActionLine key={index} action={action} />
          ))}
          {step.doing && (
            <ActionLine action={{ text: step.doing, status: "running", detail: "" }} />
          )}
        </Trace>
      </TraceCollapsibleContent>
    </TraceCollapsible>
  );
}

function ActionLine({ action }: { action: AgentAction }) {
  const line = (
    <TraceLine status={actionStatus(action)}>
      <ActionIcon text={action.text} />
      <TraceTitle>{action.text}</TraceTitle>
    </TraceLine>
  );
  if (!action.detail) return line;

  return (
    <TraceCollapsible>
      <TraceCollapsibleTrigger>{line}</TraceCollapsibleTrigger>
      <TraceCollapsibleContent className="font-mono text-xs whitespace-pre-wrap">
        {action.detail}
      </TraceCollapsibleContent>
    </TraceCollapsible>
  );
}

/**
 * An agent run as a shadcn Trace: the steps it has reached so far, one after another, each with
 * the concrete actions it took inside.
 */
export function AgentTrace({ run }: { run: TracedRun }) {
  return (
    <Trace aria-label="Steps" aria-live="polite">
      {stepGroups(run).map((step) => (
        <StepLine key={step.key} step={step} />
      ))}
    </Trace>
  );
}
