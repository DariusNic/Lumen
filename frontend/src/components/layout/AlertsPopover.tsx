import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Bell,
  Calendar,
  Flag,
  PieChart,
  Repeat,
  TrendingDown,
  TrendingUp,
  Wallet,
  type LucideIcon,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { listAlerts, markRead, type Alert } from "@/api/alerts.api";
import { qk } from "@/lib/queryKeys";
import { cn } from "@/lib/utils";

const ICON_MAP: Record<Alert["icon"], LucideIcon> = {
  "pie-chart": PieChart,
  "alert-triangle": AlertTriangle,
  "trending-up": TrendingUp,
  "trending-down": TrendingDown,
  flag: Flag,
  repeat: Repeat,
  calendar: Calendar,
  wallet: Wallet,
};

const SEVERITY_TONE: Record<Alert["severity"], string> = {
  critical: "bg-danger/10 text-danger",
  warning: "bg-warning/15 text-warning-700",
  info: "bg-primary-tint text-primary",
};

const PREVIEW_LIMIT = 5;

export function AlertsPopover() {
  const navigate = useNavigate();
  const qc = useQueryClient();

  const { data } = useQuery({
    queryKey: qk.alerts.list(),
    queryFn: listAlerts,
    staleTime: 60_000,
    // Topbar bell stays current as the user navigates around.
    refetchOnWindowFocus: true,
  });

  const markReadMutation = useMutation({
    mutationFn: (ids: string[] | undefined) => markRead(ids),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.alerts.all() });
    },
  });

  const alerts = data?.alerts ?? [];
  const unread = data?.unread_count ?? 0;
  const preview = alerts.slice(0, PREVIEW_LIMIT);

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="relative"
          aria-label={`Alerts${unread > 0 ? ` — ${unread} unread` : ""}`}
        >
          <Bell className="h-5 w-5" />
          {unread > 0 && (
            <span className="absolute right-1.5 top-1.5 h-2 w-2 rounded-full bg-danger ring-2 ring-surface" />
          )}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="end"
        className="w-[360px] p-0"
        sideOffset={8}
      >
        <div className="flex items-center justify-between border-b border-border px-md py-3">
          <div>
            <div className="text-body-small font-semibold text-text-primary">Alerts</div>
            <div className="text-uppercase-label uppercase text-text-muted">
              {unread > 0 ? `${unread} unread` : "All caught up"}
            </div>
          </div>
          {unread > 0 && (
            <button
              type="button"
              onClick={() => markReadMutation.mutate(undefined)}
              disabled={markReadMutation.isPending}
              className="text-uppercase-label uppercase text-primary hover:underline focus-ring rounded disabled:opacity-50"
            >
              Mark all read
            </button>
          )}
        </div>

        {alerts.length === 0 ? (
          <div className="px-md py-lg text-center text-body-small text-text-muted">
            No active alerts.
          </div>
        ) : (
          <ul className="max-h-[360px] divide-y divide-border overflow-y-auto">
            {preview.map((a) => {
              const Icon = ICON_MAP[a.icon] ?? AlertTriangle;
              return (
                <li key={a.id}>
                  <button
                    type="button"
                    onClick={() => {
                      if (a.unread) markReadMutation.mutate([a.id]);
                      navigate(a.link);
                    }}
                    className={cn(
                      "flex w-full items-start gap-3 px-md py-3 text-left transition-colors hover:bg-surface-soft focus-ring",
                      a.unread && "bg-primary-tint/20",
                    )}
                  >
                    <span
                      className={cn(
                        "flex h-8 w-8 shrink-0 items-center justify-center rounded-full",
                        SEVERITY_TONE[a.severity],
                      )}
                    >
                      <Icon className="h-4 w-4" />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-1.5">
                        <span className="truncate text-body-small font-medium text-text-primary">
                          {a.title}
                        </span>
                        {a.unread && (
                          <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-primary" />
                        )}
                      </span>
                      <span className="mt-0.5 line-clamp-2 block text-uppercase-label uppercase text-text-muted">
                        {a.message}
                      </span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}

        <div className="border-t border-border p-2">
          <button
            type="button"
            onClick={() => navigate("/alerts")}
            className="block w-full rounded-md px-3 py-2 text-center text-body-small font-medium text-primary hover:bg-primary-tint focus-ring"
          >
            View all alerts
          </button>
        </div>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
