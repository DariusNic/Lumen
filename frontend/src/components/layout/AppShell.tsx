import { Outlet } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";
import { IntelligencePanel } from "./IntelligencePanel";

export function AppShell() {
  return (
    <div className="flex h-screen w-full overflow-hidden bg-background text-text-primary">
      {/* Left rail — desktop only; mobile uses Topbar's drawer */}
      <Sidebar className="hidden md:flex" />

      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar />
        <div className="flex min-h-0 flex-1 overflow-hidden">
          {/* Main scrollable column. No max-width here — the sidebar +
              intelligence-panel widths already constrain the column on wide
              screens. Capping `max-w` again would leave dead whitespace on
              the right at 1600px+. The grids inside each page handle their
              own column counts responsively. */}
          <main className="min-w-0 flex-1 overflow-y-auto">
            <div className="w-full px-md py-lg md:px-lg md:py-xl">
              <Outlet />
            </div>
          </main>

          {/* Right intelligence panel — visible on xl+ only; topbar opens it as a sheet on mobile/tablet */}
          <IntelligencePanel className="hidden xl:flex" />
        </div>
      </div>
    </div>
  );
}
