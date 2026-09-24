import { CourseMaterials } from "@/components/dashboard/course-materials";

export default function Dashboard() {
  return (
    <div className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-6 px-4 py-10 sm:px-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold tracking-tight">Course materials</h1>
        <p className="text-muted-foreground">
          Upload the syllabus and reading materials for your course.
        </p>
      </header>

      <CourseMaterials />
    </div>
  );
}
