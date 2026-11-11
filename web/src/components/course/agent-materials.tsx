"use client";

import { useCallback, useEffect, useState } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { ApiError, getAgentCourse, type AgentCourse } from "@/lib/api";

const POLL_MS = 2000;

function errorMessage(err: unknown) {
  return err instanceof ApiError
    ? err.message
    : "Couldn't reach the server. Please try again.";
}

export type AgentState = {
  /** undefined while loading; null when the agent never ran for this course. */
  data: AgentCourse | null | undefined;
  loadError: string | null;
  /** The agent is working on the course right now. */
  working: boolean;
  refresh: () => Promise<void>;
};

/** The AI Note Taker's state for a course, polled while a run is going. Off for courses
 * that are not from Moodle. */
export function useAgentCourse(course: string, enabled: boolean): AgentState {
  const [data, setData] = useState<AgentCourse | null | undefined>(
    enabled ? undefined : null,
  );
  const [loadError, setLoadError] = useState<string | null>(null);

  const refresh = useCallback(
    () =>
      enabled
        ? getAgentCourse(course).then(
            (next) => {
              setData(next);
              setLoadError(null);
            },
            (err) => {
              if (err instanceof ApiError && err.status === 404) {
                setData(null);
                setLoadError(null);
              } else {
                setLoadError(errorMessage(err));
              }
            },
          )
        : Promise.resolve(),
    [course, enabled],
  );

  useEffect(() => {
    refresh();
  }, [refresh]);

  const working = data?.latest_run?.status === "running";
  useEffect(() => {
    if (!working) return;
    const timer = setInterval(refresh, POLL_MS);
    return () => clearInterval(timer);
  }, [working, refresh]);

  return { data, loadError, working, refresh };
}

/** The AI Note Taker's final report on its last run. Developer output: shown only in developer mode. */
export function AgentReport({ agent }: { agent: AgentState }) {
  const run = agent.data?.latest_run;
  if (run?.status !== "succeeded" || !run.report) return null;
  return (
    <Alert>
      <AlertTitle>Agent report</AlertTitle>
      <AlertDescription className="whitespace-pre-wrap">{run.report}</AlertDescription>
    </Alert>
  );
}
