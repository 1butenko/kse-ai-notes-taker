"use client";

import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { isActive } from "@/components/dashboard/notes-stage";
import {
  ApiError,
  generateNotes,
  getNotesRun,
  listNotesRuns,
  type NotesRun,
  type NotesRunView,
} from "@/lib/api";

const POLL_MS = 3000;

function newestFirst(runs: NotesRun[]) {
  return [...runs].sort((a, b) => b.id.localeCompare(a.id));
}

/**
 * The course's notes as the course page shows them: the latest finished run, plus the
 * run in progress, polled until it ends. Older runs live under Previous generations.
 */
export function useCourseNotes(course: string) {
  const [runs, setRuns] = useState<NotesRun[] | null>(null);
  const [done, setDone] = useState<NotesRunView | null>(null);
  const [starting, setStarting] = useState(false);

  const reload = useCallback(() => {
    listNotesRuns(course).then(
      (loaded) => setRuns(newestFirst(loaded)),
      () => setRuns((prev) => prev ?? []),
    );
  }, [course]);

  useEffect(reload, [reload]);

  const latest = runs?.[0] ?? null;
  const active = latest && isActive(latest) ? latest : null;
  const finished = runs?.find((r) => r.status === "done") ?? null;
  const finishedId = finished?.id ?? null;

  useEffect(() => {
    if (!finishedId) return;
    let cancelled = false;
    getNotesRun(course, finishedId).then(
      (view) => !cancelled && setDone(view),
      () => {},
    );
    return () => {
      cancelled = true;
    };
  }, [course, finishedId]);

  const activeId = active?.id ?? null;
  useEffect(() => {
    if (!activeId) return;
    const timer = setInterval(() => {
      getNotesRun(course, activeId).then(
        ({ run }) =>
          setRuns((prev) => newestFirst([run, ...(prev ?? []).filter((r) => r.id !== run.id)])),
        () => {},
      );
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [course, activeId]);

  const generate = async (resume?: string) => {
    setStarting(true);
    try {
      const started = await generateNotes(course, resume);
      setRuns((prev) =>
        newestFirst([started.run, ...(prev ?? []).filter((r) => r.id !== started.run.id)]),
      );
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Couldn't reach the server.");
    } finally {
      setStarting(false);
    }
  };

  return {
    loading: runs === null,
    latest,
    active,
    done: done && done.run.id === finishedId ? done : null,
    starting,
    generate,
    reload,
  };
}
