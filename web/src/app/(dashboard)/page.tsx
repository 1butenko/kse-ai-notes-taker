import { CourseWorkflow } from "@/components/dashboard/course-workflow";

export default function Dashboard() {
  return (
    <div className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-6 px-4 py-10 sm:px-6">
      <CourseWorkflow />
    </div>
  );
}
