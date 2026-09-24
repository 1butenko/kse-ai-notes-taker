import { ReadingMaterialsUpload } from "@/components/dashboard/reading-materials-upload";
import { SyllabusUpload } from "@/components/dashboard/syllabus-upload";
import { SidebarTrigger } from "@/components/ui/sidebar";

export default function Dashboard() {
  return (
    <div className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-6 px-4 py-10 sm:px-6">
      <header className="flex items-start gap-3">
        <SidebarTrigger className="mt-0.5" />
        <div className="flex flex-col gap-1">
          <h1 className="text-2xl font-semibold tracking-tight">Course materials</h1>
          <p className="text-muted-foreground">
            Upload the syllabus and reading materials for your course.
          </p>
        </div>
      </header>

      <div className="grid gap-6 lg:grid-cols-2 lg:items-start">
        <SyllabusUpload />
        <ReadingMaterialsUpload />
      </div>
    </div>
  );
}
