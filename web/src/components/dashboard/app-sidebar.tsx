import { Sidebar, SidebarHeader } from "@/components/ui/sidebar";

export function AppSidebar() {
  return (
    <Sidebar>
      <SidebarHeader className="px-4 py-4">
        <span className="text-lg font-semibold tracking-tight">KSE Notes</span>
      </SidebarHeader>
    </Sidebar>
  );
}
