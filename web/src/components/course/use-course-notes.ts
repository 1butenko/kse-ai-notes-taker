"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { isActive } from "@/components/dashboard/notes-stage";
import {
  ApiError,
  generateAllLectures,
  generateLectureNotes,
  getNotesQueue,
  getNotesRun,
  listNotesRuns,
  stopNotes,
  type NotesQueue,
  type NotesRun,
  type NotesRunView,
  type SessionView,
} from "@/lib/api";

const POLL_MS = 3000;
const IDLE: NotesQueue = { waiting: [], active: null, active_session: null, skipped: [] };

function newestFirst(runs: NotesRun[]) {
  return [...runs].sort((a, b) => b.id.localeCompare(a.id));
}

function errorMessage(err: unknown) {
  return err instanceof ApiError ? err.message : "Couldn't reach the server.";
}

/** One lecture's notes: its runs (newest first), the note it shows and what is under way. */
export type LectureNotes = {
  runs: NotesRun[];
  /** The newest finished run: the lecture's note. */
  note: NotesRun | null;
  /** The note's view (its topics), once loaded. */
  view: NotesRunView | null;
  /** The run being written for this lecture. */
  active: NotesRun | null;
  /** A stopped or failed run newer than the note; it can be resumed. */
  unfinished: NotesRun | null;
  /** Waiting in the course's queue. */
  queued: boolean;
  /** Finished runs before the note, newest first. */
  previous: NotesRun[];
};

export type LectureStatus = "none" | "queued" | "writing" | "note" | "verified" | "unresolved";

export function lectureStatus(lecture: LectureNotes): LectureStatus {
  if (lecture.active) return "writing";
  if (lecture.queued) return "queued";
  return noteStatus(lecture);
}

/** The state of the note itself, whatever is under way: settled once every topic is verified
 * or approved by the teacher. */
export function noteStatus(lecture: LectureNotes): "none" | "note" | "verified" | "unresolved" {
  if (!lecture.note) return "none";
  const topics = lecture.view?.document?.sections.flatMap((s) => s.topics);
  if (!topics) return "note";
  const settled = topics.every(
    (t) => t.status === "verified" || t.teacher_decision?.decision === "approved",
  );
  return settled ? "verified" : "unresolved";
}

/** The note was written from other readings than the lecture has now. */
export function readingsChanged(lecture: LectureNotes, entry: SessionView) {
  return Boolean(lecture.note?.materials && lecture.note.materials !== entry.materials);
}

/** Sections of the note that failed; Retry writes only these again, in a new run. */
export function failedSections(lecture: LectureNotes) {
  return (lecture.view?.document?.sections.flatMap((s) => s.topics) ?? []).filter(
    (t) => t.status === "failed",
  );
}

/**
 * The course's lecture notes: every run, the queue, and each lecture's note. Polled while a
 * lecture is being written or waits. Whole-course runs are kept apart as `legacy`.
 */
export function useCourseNotes(course: string) {
  const [runs, setRuns] = useState<NotesRun[] | null>(null);
  const [queue, setQueue] = useState<NotesQueue>(IDLE);
  const [views, setViews] = useState<Record<string, NotesRunView>>({});
  const [starting, setStarting] = useState(false);

  const reload = useCallback(
    () =>
      Promise.all([listNotesRuns(course), getNotesQueue(course).catch(() => IDLE)]).then(
        ([loaded, waiting]) => {
          setRuns(newestFirst(loaded));
          setQueue(waiting);
        },
        () => setRuns((prev) => prev ?? []),
      ),
    [course],
  );

  useEffect(() => {
    reload();
  }, [reload]);

  const busy =
    (runs?.some(isActive) ?? false) || queue.waiting.length > 0 || queue.active !== null;
  useEffect(() => {
    if (!busy) return;
    const timer = setInterval(reload, POLL_MS);
    return () => clearInterval(timer);
  }, [busy, reload]);

  const lectureRuns = useMemo(() => (runs ?? []).filter((r) => r.session_id), [runs]);

  // Each lecture's note needs its topics for the lecture's status.
  const noteIds = useMemo(() => {
    const seen = new Set<string>();
    const ids: string[] = [];
    for (const run of lectureRuns) {
      if (run.status !== "done" || seen.has(run.session_id!)) continue;
      seen.add(run.session_id!);
      ids.push(run.id);
    }
    return ids;
  }, [lectureRuns]);
  const missing = noteIds.filter((id) => !views[id]).join(",");

  useEffect(() => {
    if (!missing) return;
    let cancelled = false;
    for (const id of missing.split(",")) {
      getNotesRun(course, id).then(
        (view) => !cancelled && setViews((prev) => ({ ...prev, [id]: view })),
        () => {},
      );
    }
    return () => {
      cancelled = true;
    };
  }, [course, missing]);

  const lecture = useCallback(
    (sessionId: string): LectureNotes => {
      const own = lectureRuns.filter((r) => r.session_id === sessionId);
      const note = own.find((r) => r.status === "done") ?? null;
      const latest = own[0] ?? null;
      return {
        runs: own,
        note,
        view: note ? (views[note.id] ?? null) : null,
        active: own.find(isActive) ?? null,
        unfinished: latest?.status === "failed" ? latest : null,
        queued: queue.waiting.includes(sessionId),
        previous: own.filter((r) => r.status === "done" && r.id !== note?.id),
      };
    },
    [lectureRuns, views, queue],
  );

  const act = async <T,>(action: () => Promise<T>): Promise<T | null> => {
    setStarting(true);
    try {
      return await action();
    } catch (err) {
      toast.error(errorMessage(err));
      return null;
    } finally {
      setStarting(false);
      await reload();
    }
  };

  return {
    loading: runs === null,
    runs: runs ?? [],
    legacy: (runs ?? []).filter((r) => !r.session_id),
    queue,
    busy,
    starting,
    active: (runs ?? []).find(isActive) ?? null,
    lecture,
    reload,
    generate: (sessionId: string, from?: { resume: string } | { retry: string }) =>
      act(() => generateLectureNotes(course, sessionId, from)),
    generateAll: () => act(() => generateAllLectures(course)),
    stop: () => act(() => stopNotes(course)),
  };
}

export type CourseNotes = ReturnType<typeof useCourseNotes>;
