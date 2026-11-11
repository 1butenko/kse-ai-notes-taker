import type { Metadata } from "next";

import { VisualNotesViewer } from "@/components/lecture-notes/visual-notes-viewer";

export const metadata: Metadata = { title: "Notes · KSE Notes" };

export default async function VisualNotes(
  props: PageProps<"/lectures/[course]/[session]/visual/[[...run]]">,
) {
  const { course, session, run } = await props.params;
  return <VisualNotesViewer course={course} sessionId={session} runId={run?.[0]} />;
}
