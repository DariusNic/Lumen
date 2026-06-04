import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  ArrowRight,
  BellOff,
  Calendar,
  Flag,
  Loader2,
  Mail,
  PieChart,
  Repeat,
  TrendingDown,
  TrendingUp,
  Wallet,
  type LucideIcon,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { SectionCard } from "@/components/shared/SectionCard";
import { EmptyState } from "@/components/shared/EmptyState";
import { cn } from "@/lib/utils";
import { qk } from "@/lib/queryKeys";
import { parseApiError } from "@/api/client";
import { listAlerts, markRead, type Alert } from "@/api/alerts.api";

type SortKey = "severe-desc" | "severe-asc" | "time-desc" | "time-asc";

const SORT_OPTIONS: { value: SortKey; label: string }[] = [
  { value: "severe-desc", label: "Most severe first" },
  { value: "severe-asc", label: "Least severe first" },
  { value: "time-desc", label: "Newest first" },
  { value: "time-asc", label: "Oldest first" },
];

const SEVERITY_ORDINAL: Record<Alert["severity"], number> = {
  critical: 3,
  warning: 2,
  info: 1,
};

const SEVERITY_TONE: Record<Alert["severity"], string> = {
  critical: "bg-danger/10 text-danger",
  warning: "bg-warning/15 text-warning-700",
  info: "bg-primary-tint text-primary",
};

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

// localStorage keys for persisting the user's chosen sort/filter across
// visits. Kept under a single namespace prefix so we can clear all alert
// preferences with one call if needed.
const LS_SORT = "alerts.sort";
const LS_FILTER_CRITICAL = "alerts.show.critical";
const LS_FILTER_WARNING = "alerts.show.warning";
const LS_FILTER_INFO = "alerts.show.info";
const LS_UNREAD_ONLY = "alerts.unreadOnly";

function readStoredSort(): SortKey {
  const raw = typeof localStorage !== "undefined" ? localStorage.getItem(LS_SORT) : null;
  if (raw && SORT_OPTIONS.some((o) => o.value === raw)) return raw as SortKey;
  return "severe-desc";
}

function readStoredBool(key: string, fallback: boolean): boolean {
  if (typeof localStorage === "undefined") return fallback;
  const raw = localStorage.getItem(key);
  if (raw === "true") return true;
  if (raw === "false") return false;
  return fallback;
}

export default function AlertsPage() {
  const qc = useQueryClient();

  // All three filters default ON — feature parity with the old "show
  // everything" default. The sort defaults to severity descending so a
  // first-time visitor immediately sees critical items at the top.
  const [sort, setSort] = useState<SortKey>(() => readStoredSort());
  const [showCritical, setShowCritical] = useState(() => readStoredBool(LS_FILTER_CRITICAL, true));
  const [showWarning, setShowWarning] = useState(() => readStoredBool(LS_FILTER_WARNING, true));
  const [showInfo, setShowInfo] = useState(() => readStoredBool(LS_FILTER_INFO, true));
  // Unread-only is conceptually different from the three severity filters:
  // it's an orthogonal axis (read-state, not category). Default OFF so a
  // first-time visitor sees the full feed; rendered as a pill toggle on the
  // left of the filter row, separated by a divider, to break the visual
  // sameness of "four checkboxes lined up identically".
  const [unreadOnly, setUnreadOnly] = useState(() => readStoredBool(LS_UNREAD_ONLY, false));

  // Persist preferences on change so they stick across reloads / browser
  // sessions. No debounce needed — toggles fire at most once per click.
  useEffect(() => { localStorage.setItem(LS_SORT, sort); }, [sort]);
  useEffect(() => { localStorage.setItem(LS_FILTER_CRITICAL, String(showCritical)); }, [showCritical]);
  useEffect(() => { localStorage.setItem(LS_FILTER_WARNING, String(showWarning)); }, [showWarning]);
  useEffect(() => { localStorage.setItem(LS_FILTER_INFO, String(showInfo)); }, [showInfo]);
  useEffect(() => { localStorage.setItem(LS_UNREAD_ONLY, String(unreadOnly)); }, [unreadOnly]);

  const { data, isLoading, isError, error } = useQuery({
    queryKey: qk.alerts.list(),
    queryFn: listAlerts,
    staleTime: 60_000,
  });

  const markReadMutation = useMutation({
    mutationFn: (ids: string[] | undefined) => markRead(ids),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.alerts.all() });
    },
  });

  const items = data?.alerts ?? [];
  const unreadCount = data?.unread_count ?? 0;

  // Apply severity checkboxes, then sort.
  // - Severity sorts use time as the secondary key so within "all critical"
  //   the newest still comes first (or oldest first if ascending time would
  //   imply that — kept descending here because "show me the worst, recent")
  // - Time sorts use severity as the secondary key so two alerts with the
  //   same timestamp (common, since alerts are generated fresh per request)
  //   still surface critical above info.
  const visible = useMemo(() => {
    const filtered = items.filter((a) => {
      if (unreadOnly && !a.unread) return false;
      if (a.severity === "critical") return showCritical;
      if (a.severity === "warning") return showWarning;
      if (a.severity === "info") return showInfo;
      return true;
    });
    const cmp = (a: Alert, b: Alert): number => {
      const sevA = SEVERITY_ORDINAL[a.severity];
      const sevB = SEVERITY_ORDINAL[b.severity];
      const timeA = new Date(a.timestamp).getTime();
      const timeB = new Date(b.timestamp).getTime();
      switch (sort) {
        case "severe-desc": return sevB - sevA || timeB - timeA;
        case "severe-asc":  return sevA - sevB || timeB - timeA;
        case "time-desc":   return timeB - timeA || sevB - sevA;
        case "time-asc":    return timeA - timeB || sevB - sevA;
      }
    };
    return [...filtered].sort(cmp);
  }, [items, showCritical, showWarning, showInfo, unreadOnly, sort]);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center gap-2 py-2xl text-body-small text-text-muted">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading alerts…
      </div>
    );
  }

  if (isError) {
    return (
      <SectionCard title="Alerts">
        <p className="text-body-small text-danger">{parseApiError(error)}</p>
      </SectionCard>
    );
  }

  if (items.length === 0) {
    return (
      <EmptyState
        icon={BellOff}
        title="All clear"
        description="You don't have any active alerts. We'll notify you when budgets are at risk, when goals fall behind, or when planned payments are due."
      />
    );
  }

  return (
    <div className="space-y-lg animate-fade-in">
      <header className="flex flex-wrap items-center justify-between gap-md">
        <div>
          <h1 className="text-h2 font-h2 text-text-primary">Alerts</h1>
          <p className="text-body-small text-text-muted">
            {unreadCount} unread · showing {visible.length} of {items.length}
          </p>
        </div>
        <Button
          variant="ghost"
          size="sm"
          disabled={unreadCount === 0 || markReadMutation.isPending}
          onClick={() => markReadMutation.mutate(undefined)}
        >
          Mark all as read
        </Button>
      </header>

      <div className="flex flex-wrap items-center gap-md rounded-lg border border-border bg-surface-soft px-md py-3">
        <label className="flex items-center gap-2 text-body-small text-text-muted">
          <span className="text-uppercase-label uppercase">Sort by</span>
          <select
            value={sort}
            onChange={(e) => setSort(e.target.value as SortKey)}
            className="h-9 rounded-md border border-border bg-surface px-2 text-body-small text-text-primary focus-ring"
          >
            {SORT_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </label>

        <div className="ml-auto flex flex-wrap items-center gap-3">
          {/* Pill toggle — visually distinct from the three severity checkboxes
              that follow. Read-state is an orthogonal axis (any severity can
              be read or unread), so the divider signals "different category
              of filter" to the user. */}
          <UnreadToggle
            checked={unreadOnly}
            onChange={setUnreadOnly}
            unreadCount={unreadCount}
          />
          <span aria-hidden="true" className="h-6 w-px bg-border" />
          <span className="text-uppercase-label uppercase text-text-muted">Show</span>
          <SeverityCheckbox
            label="Critical"
            tone="bg-danger/10 text-danger"
            checked={showCritical}
            onChange={setShowCritical}
          />
          <SeverityCheckbox
            label="Warning"
            tone="bg-warning/15 text-warning-700"
            checked={showWarning}
            onChange={setShowWarning}
          />
          <SeverityCheckbox
            label="Info"
            tone="bg-primary-tint text-primary"
            checked={showInfo}
            onChange={setShowInfo}
          />
        </div>
      </div>

      {visible.length === 0 ? (
        <SectionCard>
          <p className="py-md text-center text-body-small text-text-muted">
            No alerts match the current filters.
          </p>
        </SectionCard>
      ) : (
        <SectionCard noPadding>
          <ul className="divide-y divide-border">
            {visible.map((a) => {
              const Icon = ICON_MAP[a.icon] ?? AlertTriangle;
              return (
                <li
                  key={a.id}
                  className={cn(
                    "flex items-start gap-md px-md py-3 transition-colors hover:bg-surface-soft",
                    a.unread && "bg-primary-tint/30",
                  )}
                >
                  <span
                    className={cn(
                      "flex h-10 w-10 shrink-0 items-center justify-center rounded-full",
                      SEVERITY_TONE[a.severity],
                    )}
                  >
                    <Icon className="h-5 w-5" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-text-primary">{a.title}</span>
                      {a.unread && <span className="h-2 w-2 rounded-full bg-primary" />}
                    </div>
                    <p className="mt-0.5 text-body-small text-text-muted">{a.message}</p>
                    <div className="mt-1.5 flex items-center gap-3">
                      <Link
                        to={a.link}
                        onClick={() => {
                          if (a.unread) markReadMutation.mutate([a.id]);
                        }}
                        className="inline-flex items-center gap-1 text-body-small font-medium text-primary hover:underline focus-ring rounded"
                      >
                        View detail <ArrowRight className="h-3 w-3" />
                      </Link>
                      {a.unread && (
                        <button
                          type="button"
                          onClick={() => markReadMutation.mutate([a.id])}
                          className="text-uppercase-label uppercase text-text-muted hover:text-text-primary focus-ring rounded"
                        >
                          Mark as read
                        </button>
                      )}
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>
        </SectionCard>
      )}
    </div>
  );
}

/** Pill-style toggle for the read-state axis. Renders as a single
 *  pressable button (not a checkbox), with an envelope icon and the
 *  current unread count as a badge when on. Visually different from
 *  the three severity checkboxes so the user reads it as a separate
 *  category of filter, not "another box in the row". */
function UnreadToggle({
  checked,
  onChange,
  unreadCount,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  unreadCount: number;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className={cn(
        "inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-body-small font-medium transition-colors focus-ring",
        checked
          ? "border-primary bg-primary text-on-primary shadow-sm hover:bg-primary-hover"
          : "border-border bg-surface text-text-muted hover:border-primary/40 hover:text-text-primary",
      )}
    >
      <Mail className="h-3.5 w-3.5" />
      Unread only
      {unreadCount > 0 && (
        <span
          className={cn(
            "min-w-5 rounded-full px-1.5 text-uppercase-label uppercase",
            checked ? "bg-white/20 text-on-primary" : "bg-primary-tint text-primary",
          )}
        >
          {unreadCount}
        </span>
      )}
    </button>
  );
}

function SeverityCheckbox({
  label,
  tone,
  checked,
  onChange,
}: {
  label: string;
  tone: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label
      className={cn(
        "inline-flex cursor-pointer items-center gap-2 rounded-md border border-border bg-surface px-2 py-1 text-body-small transition-colors focus-within:ring-2 focus-within:ring-primary/40",
        checked ? "text-text-primary" : "text-text-muted",
      )}
    >
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="h-4 w-4 cursor-pointer accent-primary"
      />
      <span className={cn("rounded-full px-2 py-0.5 text-uppercase-label uppercase", tone)}>
        {label}
      </span>
    </label>
  );
}
