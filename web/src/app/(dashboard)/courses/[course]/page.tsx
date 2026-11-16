import type { Metadata } from "next";

import { CourseView } from "@/components/course/course-view";

export const metadata: Metadata = { title: "Course · KSE Notes" };

export default async function Course(props: PageProps<"/courses/[course]">) {
  const { course } = await props.params;
  return <CourseView key={course} course={course} />;
}
