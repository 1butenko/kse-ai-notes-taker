"use client";

import { useCallback, useEffect, useState } from "react";
import {
  CircleAlertIcon,
  DownloadIcon,
  FileTextIcon,
  PlayIcon,
} from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import {
  ApiError,
  getAgentCourse,
  startAgentSync,
  type AgentCourse,
  type AgentTopic,
} from "@/lib/api";

const POLL_MS = 2000;

function errorMessage(err: unknown) {
  return err instanceof ApiError
    ? err.message
    : "Couldn't reach the server. Please try again.";
}

function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function topicTitle(topic: AgentTopic) {
  return (
    topic.name || (topic.section === 0 ? "General" : `Section ${topic.section}`)
  );
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

function RunStatus({ course }: { course: AgentCourse }) {
  const run = course.latest_run;
  if (!run) return null;
  if (run.status === "running") {
    return (
      <Alert>
        <Spinner />
        <AlertTitle>{run.step ?? "The AI Note Taker is working"}</AlertTitle>
        <AlertDescription>
          Fetching the course&apos;s study materials from Moodle
          {run.focus ? ` about “${run.focus}”` : ""}. This updates by itself.
        </AlertDescription>
      </Alert>
    );
  }
  if (run.status === "failed") {
    return (
      <Alert variant="destructive">
        <CircleAlertIcon />
        <AlertTitle>The last run failed</AlertTitle>
        <AlertDescription className="break-words">{run.error}</AlertDescription>
      </Alert>
    );
  }
  return (
    <Alert>
      <AlertTitle>Agent report</AlertTitle>
      <AlertDescription className="whitespace-pre-wrap">
        {run.report}
      </AlertDescription>
    </Alert>
  );
}

/** Materials the AI Note Taker fetched from Moodle into S3, by Moodle section. */
export function AgentMaterials({
  course,
  agent,
}: {
  course: string;
  agent: AgentState;
}) {
  const { data, loadError, working, refresh } = agent;
  const [focus, setFocus] = useState("");
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);

  const start = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setStarting(true);
    setStartError(null);
    try {
      await startAgentSync(course, focus);
    } catch (err) {
      setStartError(errorMessage(err));
    } finally {
      setStarting(false);
      refresh();
    }
  };

  const topics =
    data?.topics.filter((topic) => topic.materials.length > 0) ?? [];

  return (
    <section
      aria-labelledby="agent-materials-title"
      className="flex flex-col gap-4 border-t pt-6"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div className="flex flex-col gap-1">
          <h2 id="agent-materials-title" className="text-xl">
            Moodle materials
          </h2>
          <p className="text-sm text-muted-foreground">
            Fetched from Moodle by the AI Note Taker and kept in S3.
          </p>
        </div>
        {data && <Badge variant="outline">{data.materials} files</Badge>}
      </div>

      {loadError && (
        <Alert variant="destructive">
          <CircleAlertIcon />
          <AlertTitle>Couldn&apos;t load the Moodle materials</AlertTitle>
          <AlertDescription>{loadError}</AlertDescription>
        </Alert>
      )}

      {data === undefined && !loadError && <Skeleton className="h-16 w-full" />}

      {data && <RunStatus course={data} />}

      {data !== undefined && (
        <form onSubmit={start} className="flex flex-col gap-2 sm:flex-row">
          <Input
            value={focus}
            onChange={(event) => setFocus(event.target.value)}
            placeholder="Focus topic (optional)"
            aria-label="Focus topic"
            className="sm:max-w-xs"
            disabled={starting || working}
          />
          <Button
            type="submit"
            variant="outline"
            disabled={starting || working}
          >
            {starting || working ? <Spinner /> : <PlayIcon />}
            {data?.latest_run ? "Run again" : "Fetch materials"}
          </Button>
        </form>
      )}
      {startError && (
        <Alert variant="destructive">
          <CircleAlertIcon />
          <AlertTitle>Couldn&apos;t start the AI Note Taker</AlertTitle>
          <AlertDescription>{startError}</AlertDescription>
        </Alert>
      )}

      {topics.map((topic) => (
        <div key={topic.section} className="flex flex-col gap-2">
          <h3 className="font-medium">{topicTitle(topic)}</h3>
          <ul className="flex flex-col border-t">
            {topic.materials.map((material) => (
              <li
                key={material.id}
                className="flex items-center gap-3 border-b py-2"
              >
                <FileTextIcon className="size-4 shrink-0 text-muted-foreground" />
                <span className="flex min-w-0 flex-1 flex-col">
                  <span
                    className="truncate text-sm font-medium"
                    title={material.name}
                  >
                    {material.name}
                  </span>
                  <span
                    className="truncate text-xs text-muted-foreground"
                    title={material.reason}
                  >
                    {formatSize(material.size)}
                    {material.reason ? ` · ${material.reason}` : ""}
                  </span>
                </span>
                <a
                  href={material.url}
                  target="_blank"
                  rel="noreferrer"
                  aria-label={`Download ${material.name}`}
                  className={buttonVariants({
                    variant: "ghost",
                    size: "icon-sm",
                  })}
                >
                  <DownloadIcon />
                </a>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </section>
  );
}
