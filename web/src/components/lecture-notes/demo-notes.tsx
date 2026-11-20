"use client";

import { VisualNotesFrame } from "@/components/lecture-notes/visual-notes-viewer";
import type { LectureNotesRun } from "@/lib/api";

function fakeRun(id: string, finishedAt: string): LectureNotesRun {
  return {
    id,
    session_id: "demo",
    session_label: "Lecture 3: Supply, demand and market equilibrium",
    status: "succeeded",
    step: null,
    todos: [],
    actions: [],
    report: null,
    error: null,
    files: ["index.html"],
    model: null,
    renders: 1,
    readings_changed: false,
    kind: "agent",
    edited_from: null,
    started_at: finishedAt,
    finished_at: finishedAt,
  };
}

const RUN = fakeRun("demo-1", "2026-11-19T10:30:00Z");

/** Development only: the notes page with a fake run and a static sample page, to work on the
 * design without the API, the database or S3. */
export function DemoNotes() {
  return (
    <VisualNotesFrame
      course="demo"
      courseName="Principles of Economics"
      loading={false}
      run={RUN}
      error={null}
      siteUrl={() => "/dev/sample-notes.html"}
    />
  );
}
