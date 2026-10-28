import type { Metadata } from "next";

import { LecturePage } from "@/components/course/lecture-page";

export const metadata: Metadata = { title: "Lecture · KSE Notes" };

export default async function Lecture(props: PageProps<"/lectures/[course]/[session]">) {
  const { course, session } = await props.params;
  return <LecturePage course={course} sessionId={session} />;
}
