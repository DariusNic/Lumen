import { NavLink, useNavigate } from "react-router-dom";
import { Logo } from "./Logo";
import { NAV_GROUPS, NAV_ITEMS } from "./nav-items";
import { cn } from "@/lib/utils";
import { ChevronUp, LogOut, Settings as SettingsIcon } from "lucide-react";
import { useAuthStore } from "@/store/authStore";
import * as authApi from "@/api/auth.api";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

interface SidebarProps {
  className?: string;
  /** Hide the brand area at top (used in mobile drawer where we have our own header) */
  compact?: boolean;
  /** Click handler bubbled up so the drawer can close on link nav */
  onNavigate?: () => void;
}

function initials(name: string | undefined): string {
  if (!name) return "??";
  const parts = name.trim().split(/\s+/);
  const first = parts[0]?.[0] ?? "";
  const last = parts.length > 1 ? parts[parts.length - 1][0] : "";
  return (first + last).toUpperCase() || "??";
}

export function Sidebar({ className, compact = false, onNavigate }: SidebarProps) {
  const user = useAuthStore((s) => s.user);
  const accessToken = useAuthStore((s) => s.accessToken);
  const clear = useAuthStore((s) => s.clear);
  const navigate = useNavigate();

  const handleLogout = async () => {
    try {
      if (accessToken) await authApi.logout(accessToken);
    } catch {
      /* logout is best-effort; we clear locally regardless */
    }
    clear();
    navigate("/auth", { replace: true });
  };

  return (
    <nav
      aria-label="Primary"
      className={cn(
        "flex h-full w-[240px] flex-col border-r border-border bg-surface",
        className,
      )}
    >
      {!compact && (
        <div className="flex h-16 items-center px-lg border-b border-border">
          <Logo />
        </div>
      )}

      <div className="flex-1 overflow-y-auto px-3 py-md">
        {NAV_GROUPS.map((group) => {
          const items = NAV_ITEMS.filter((i) => i.group === group.id);
          if (!items.length) return null;
          return (
            <div key={group.id} className="mb-md last:mb-0">
              <div className="px-3 pb-1.5 pt-2 text-uppercase-label uppercase text-text-muted">
                {group.label}
              </div>
              <ul className="space-y-0.5">
                {items.map((item) => (
                  <li key={item.href}>
                    <NavLink
                      to={item.href}
                      onClick={onNavigate}
                      className={({ isActive }) =>
                        cn(
                          "group relative flex items-center gap-3 rounded-lg px-3 py-2 text-body-small font-medium min-h-11",
                          "transition-all duration-150",
                          "focus-ring",
                          isActive
                            ? "bg-primary-tint text-primary"
                            : "text-text-muted hover:bg-surface-soft hover:text-text-primary",
                        )
                      }
                    >
                      {({ isActive }) => (
                        <>
                          {isActive && (
                            <span
                              className="absolute left-0 top-1/2 h-6 w-0.5 -translate-y-1/2 rounded-r bg-primary"
                              aria-hidden="true"
                            />
                          )}
                          <item.icon
                            className={cn(
                              "h-5 w-5 shrink-0 transition-transform group-hover:scale-105",
                              isActive ? "text-primary" : "text-text-muted",
                            )}
                          />
                          <span className="truncate">{item.label}</span>
                        </>
                      )}
                    </NavLink>
                  </li>
                ))}
              </ul>
            </div>
          );
        })}
      </div>

      <div className="border-t border-border p-3">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              className="flex w-full items-center gap-3 rounded-lg p-2 text-left transition-colors hover:bg-surface-soft focus-ring"
              aria-label="Account menu"
            >
              <div
                className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-primary text-on-primary text-body-small font-semibold"
                aria-hidden="true"
              >
                {initials(user?.full_name)}
              </div>
              <div className="min-w-0 flex-1">
                <div className="truncate text-body-small font-medium text-text-primary">
                  {user?.full_name ?? "—"}
                </div>
                <div className="truncate text-uppercase-label uppercase text-text-muted">
                  {user?.email ?? "Not signed in"}
                </div>
              </div>
              <ChevronUp className="h-4 w-4 shrink-0 text-text-muted" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent side="top" align="start" className="w-[216px]">
            <DropdownMenuItem onSelect={() => { onNavigate?.(); navigate("/settings"); }}>
              <SettingsIcon className="h-4 w-4" /> Settings
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              onSelect={handleLogout}
              className="text-danger focus:bg-danger/10 focus:text-danger"
            >
              <LogOut className="h-4 w-4" /> Sign out
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </nav>
  );
}
