import type { Metadata } from "next";

import { NotesEditorLoader } from "@/components/lecture-notes/editor/notes-editor-loader";

export const metadata: Metadata = { title: "Edit notes · KSE Notes" };

export default async function EditNotes(props: PageProps<"/lectures/[course]/[session]/edit">) {
  const { course, session } = await props.params;
  return <NotesEditorLoader course={course} sessionId={session} />;
}
