import { AppHeader } from "@/components/dashboard/app-header";
import { MoodleCourseProvider } from "@/components/dashboard/moodle-course-context";
import { verifySession } from "@/lib/dal";

export default async function DashboardLayout({ children }: LayoutProps<"/">) {
  await verifySession();
  return (
    <MoodleCourseProvider>
      <AppHeader />
      <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col px-4 py-8 sm:px-6 sm:py-10">
        {children}
      </main>
    </MoodleCourseProvider>
  );
}
