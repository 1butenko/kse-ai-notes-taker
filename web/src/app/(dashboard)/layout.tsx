import { AppSidebar } from "@/components/dashboard/app-sidebar";
import { MoodleCourseProvider } from "@/components/dashboard/moodle-course-context";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";

export default function DashboardLayout({ children }: LayoutProps<"/">) {
  return (
    <MoodleCourseProvider>
      <SidebarProvider>
        <AppSidebar />
        <SidebarInset>{children}</SidebarInset>
      </SidebarProvider>
    </MoodleCourseProvider>
  );
}
