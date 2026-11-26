import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { DemoNotes } from "@/components/lecture-notes/demo-notes";

export const metadata: Metadata = { title: "Demo notes · KSE Notes" };

/** Development only: the notes page with fake data (`public/dev/sample-notes.html`). */
export default function DemoNotesPage() {
  if (process.env.NODE_ENV !== "development") notFound();
  return <DemoNotes />;
}
