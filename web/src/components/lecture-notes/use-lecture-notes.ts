"use client";

import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import {
  ApiError,
  cancelLectureNotes,
  listLectureNotes,
  startLectureNotes,
  type LectureNotesRun,
} from "@/lib/api";

const POLL_MS = 3000;

function message(err: unknown) {
  return err instanceof ApiError ? err.message : "Couldn't reach the server. Please try again.";
}

/** One lecture's visual-notes runs, polled while one is being written. */
export function useLectureNotes(course: string, sessionId: string) {
  const [runs, setRuns] = useState<LectureNotesRun[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);

  const load = useCallback(
    () =>
      listLectureNotes(course, sessionId).then(
        (loaded) => {
          setRuns(loaded);
          setError(null);
        },
        (err) => setError(message(err)),
      ),
    [course, sessionId],
  );

  useEffect(() => {
    load();
  }, [load]);

  const active = runs?.find((r) => r.status === "running") ?? null;
  const latest = runs?.[0] ?? null;
  const published = runs?.filter((r) => r.status === "succeeded") ?? [];

  useEffect(() => {
    if (!active) return;
    const timer = setInterval(load, POLL_MS);
    return () => clearInterval(timer);
  }, [active, load]);

  const start = async () => {
    setStarting(true);
    try {
      const run = await startLectureNotes(course, sessionId);
      setRuns((current) => [run, ...(current ?? [])]);
    } catch (err) {
      toast.error(message(err));
    } finally {
      setStarting(false);
    }
  };

  const cancel = async () => {
    if (!active) return;
    setStarting(true);
    try {
      await cancelLectureNotes(active.id);
      await load();
    } catch (err) {
      toast.error(message(err));
    } finally {
      setStarting(false);
    }
  };

  return { runs, error, active, latest, published, starting, start, cancel, reload: load };
}
