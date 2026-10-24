"use client";

import { useEffect, useState } from "react";
import { DownloadIcon } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button, buttonVariants } from "@/components/ui/button";
import {
  getNotesRun,
  getRenderJob,
  renderNotesRevision,
  revisionArtifactUrl,
  type RenderJob,
} from "@/lib/api";

type Props = {
  course: string;
  run: string;
  revision: number;
  refresh: () => Promise<unknown>;
};

async function hasWord(url: string): Promise<boolean> {
  const response = await fetch(url, { headers: { Range: "bytes=0-0" } });
  await response.body?.cancel();
  if (response.status === 404) return false;
  if (response.ok) return true;
  throw new Error(`Could not check the Word file (${response.status})`);
}

/** One immutable revision's Word file; the URL never falls back to another revision. */
export function RevisionWord({ course, run, revision, refresh }: Props) {
  const url = revisionArtifactUrl(course, run, revision, "docx");
  const storageKey = `notes-word-job/${course}/${run}/${revision}`;
  const [ready, setReady] = useState<boolean | null>(null);
  const [job, setJob] = useState<RenderJob | null>(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const savedJob = window.sessionStorage.getItem(storageKey);
        const [file, previous] = await Promise.all([
          hasWord(url),
          savedJob ? getRenderJob(course, run, savedJob) : getNotesRun(course, run).then((view) => view.render),
        ]);
        if (cancelled) return;
        setReady(file);
        if (previous?.revision === revision && previous.formats.includes("docx")) setJob(previous);
      } catch (cause) {
        if (!cancelled) {
          setReady(false);
          setError(cause instanceof Error ? cause.message : "Could not check the Word file");
        }
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [course, run, revision, storageKey, url]);

  const pendingJob = job && (job.status === "queued" || job.status === "running") ? job.id : null;
  useEffect(() => {
    if (!pendingJob) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const next = await getRenderJob(course, run, pendingJob);
        if (cancelled) return;
        setJob(next);
        if (next.status === "done") {
          setReady(await hasWord(url));
          await refresh();
        }
      } catch (cause) {
        if (!cancelled) setError(cause instanceof Error ? cause.message : "Could not check Word preparation");
      }
      if (!cancelled) timer = setTimeout(poll, 1_000);
    };
    timer = setTimeout(poll, 500);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [course, run, pendingJob, refresh, url]);

  const prepare = async () => {
    setStarting(true);
    setError(null);
    try {
      const next = await renderNotesRevision(course, run, revision, ["docx"]);
      window.sessionStorage.setItem(storageKey, next.id);
      setJob(next);
      setReady(false);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not start Word preparation");
    } finally {
      setStarting(false);
    }
  };

  const pending = starting || job?.status === "queued" || job?.status === "running";
  const failed = job?.status === "failed" && !ready;

  return (
    <div role="group" aria-label={`Word for revision ${revision}`} className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        {ready && !pending ? (
          <a href={url} download className={buttonVariants({ variant: "outline", size: "sm" })}>
            <DownloadIcon /> Download Word · revision {revision}
          </a>
        ) : (
          <Button size="sm" variant="outline" disabled={pending || ready === null} onClick={prepare}>
            <DownloadIcon />
            {pending ? "Preparing Word…" : failed ? "Retry Word" : "Prepare Word"} · revision {revision}
          </Button>
        )}
        {pending && (
          <span role="status" className="text-xs text-muted-foreground">
            {job?.status === "queued" ? "Queued" : "Running"} for revision {revision}.
          </span>
        )}
      </div>
      {(failed || error) && (
        <Alert variant="destructive">
          <AlertTitle>Could not prepare Word for revision {revision}</AlertTitle>
          <AlertDescription>
            <p>Your saved text, HTML and PDF are kept.</p>
            {job?.errors.map((message, index) => <p key={index}>{message}</p>)}
            {error && <p>{error}</p>}
          </AlertDescription>
        </Alert>
      )}
    </div>
  );
}
