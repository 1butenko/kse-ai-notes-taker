import { AppHeader } from "@/components/dashboard/app-header";
import { MoodleCourseProvider } from "@/components/dashboard/moodle-course-context";
import { verifySession } from "@/lib/dal";

/** The signed-in shell: the app bar over the page. Pages in `(page)` get the centred column;
 * the notes viewer fills the whole width. */
export default async function DashboardLayout({ children }: LayoutProps<"/">) {
  await verifySession();
  return (
    <MoodleCourseProvider>
      <AppHeader />
      {children}
    </MoodleCourseProvider>
  );
}
