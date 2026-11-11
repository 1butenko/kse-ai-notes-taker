"use client";

import { useCallback, useEffect, useState } from "react";

import { listCourseLectureNotes, type LectureNotesStatus } from "@/lib/api";

const POLL_MS = 5000;

export type LectureNotesState = "none" | "writing" | "ready" | "changed" | "failed";

/** What the lecture list shows for one lecture's notes. */
export function notesState(status: LectureNotesStatus | undefined): LectureNotesState {
  if (!status) return "none";
  if (status.latest.status === "running") return "writing";
  if (status.published) return status.published.readings_changed ? "changed" : "ready";
  return "failed";
}

/** Every lecture's notes in a course, polled while one is being written. */
export function useCourseLectureNotes(course: string) {
  const [statuses, setStatuses] = useState<Map<string, LectureNotesStatus> | null>(null);

  const load = useCallback(
    () =>
      listCourseLectureNotes(course).then(
        (items) => setStatuses(new Map(items.map((item) => [item.session_id, item]))),
        // Without the database (or before the course is linked) every lecture shows "No notes".
        () => setStatuses((current) => current ?? new Map()),
      ),
    [course],
  );

  useEffect(() => {
    load();
  }, [load]);

  const busy = [...(statuses?.values() ?? [])].some((s) => s.latest.status === "running");
  useEffect(() => {
    if (!busy) return;
    const timer = setInterval(load, POLL_MS);
    return () => clearInterval(timer);
  }, [busy, load]);

  return {
    loaded: statuses !== null,
    busy,
    status: (sessionId: string) => statuses?.get(sessionId),
    reload: load,
  };
}

export type CourseLectureNotes = ReturnType<typeof useCourseLectureNotes>;
