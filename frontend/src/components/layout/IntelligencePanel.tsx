import { useMemo } from "react";
import { ArrowRight, Bell, Loader2, TrendingDown, TrendingUp } from "lucide-react";
import { Area, AreaChart, ResponsiveContainer } from "recharts";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { cn } from "@/lib/utils";
import { SignalPill } from "@/components/shared/SignalBadge";
import { formatMoney } from "@/lib/format";
import { useCurrency } from "@/hooks/useCurrency";
import { useFxRate } from "@/hooks/useFxRate";
import { qk } from "@/lib/queryKeys";
import * as catApi from "@/api/categories.api";
import * as portfolioApi from "@/api/portfolio.api";
import * as recApi from "@/api/recurring.api";
import * as reportsApi from "@/api/reports.api";
import * as stocksApi from "@/api/stocks.api";

interface IntelligencePanelProps {
  className?: string;
}

/**
 * Right-side intelligence panel. Lives in the desktop layout (always visible
 * on `lg+`) and as a slide-over `Sheet` triggered from the topbar on smaller
 * screens. All four sections are driven by live APIs; each one degrades to
 * a quiet skeleton/empty hint when its data isn't available, never crashing
 * the whole panel.
 */
export function IntelligencePanel({ className }: IntelligencePanelProps) {
  return (
    <aside
      aria-label="Intelligence panel"
      className={cn(
        "flex h-full w-[320px] shrink-0 flex-col gap-md overflow-y-auto border-l border-border bg-background p-md",
        className,
      )}
    >
      <SignalsCard />
      <PortfolioCard />
      <UpcomingCard />
      <BudgetsNearLimitCard />
      <Link
        to="/alerts"
        className="flex items-center gap-3 rounded-xl border border-border bg-surface p-md text-body-small shadow-card transition-all hover:border-outline hover:shadow-card-hover focus-ring"
      >
        <div className="flex h-9 w-9 items-center justify-center rounded-full bg-primary-tint text-primary">
          <Bell className="h-4 w-4" />
        </div>
        <div className="flex-1">
          <div className="font-medium text-text-primary">Alerts</div>
          <div className="text-text-muted">View notifications</div>
        </div>
        <ArrowRight className="h-4 w-4 text-text-muted" />
      </Link>
    </aside>
  );
}


// ---------------------------------------------------------------------------
// Strong AI signals (top 3 high-confidence BUY/SELL from the batch endpoint)
// ---------------------------------------------------------------------------

function SignalsCard() {
  const signalsQuery = useQuery({
    queryKey: qk.stocks.signalsBatch(),
    queryFn: stocksApi.getAllSignals,
    staleTime: 30 * 60_000,
  });

  // Top 3 strongest BUY or SELL signals — HOLD is by definition uncertain,
  // so it doesn't count as "strong". Sort by confidence desc.
  const top = useMemo(() => {
    const sigs = signalsQuery.data?.signals ?? [];
    return sigs
      .filter((s) => s.label === "BUY" || s.label === "SELL")
      .sort((a, b) => b.confidence - a.confidence)
      .slice(0, 3);
  }, [signalsQuery.data]);

  return (
    <Card title="Strong AI signals" actionTo="/markets" actionLabel="All">
      {signalsQuery.isLoading ? (
        <Skeleton lines={3} />
      ) : signalsQuery.isError ? (
        <Hint>Signals unavailable.</Hint>
      ) : top.length === 0 ? (
        <Hint>No strong BUY/SELL signals right now.</Hint>
      ) : (
        <ul className="space-y-2">
          {top.map((s) => (
            <li
              key={s.ticker}
              className="flex items-center justify-between gap-md rounded-lg border border-border/60 px-3 py-2 transition-all hover:border-outline hover:bg-surface-soft"
            >
              <Link
                to={`/stocks/${s.ticker}`}
                className="font-mono text-body font-semibold tracking-tight focus-ring rounded"
              >
                {s.ticker}
              </Link>
              <SignalPill signal={s.label} confidence={s.confidence} />
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}


// ---------------------------------------------------------------------------
// Portfolio value (paper-trading total value + return % + 3M sparkline).
// Same data the /portfolio page uses, condensed into the right-rail card.
// ---------------------------------------------------------------------------

function PortfolioCard() {
  const baseCurrency = useCurrency();
  const usdToBase = useFxRate("USD", baseCurrency);
  const portfolioQuery = useQuery({
    queryKey: qk.portfolio.current(),
    queryFn: portfolioApi.getPortfolio,
  });
  const historyQuery = useQuery({
    queryKey: qk.portfolio.history("3M"),
    queryFn: () => portfolioApi.getHistory("3M"),
  });

  const portfolio = portfolioQuery.data;
  const sparkData = (historyQuery.data?.points ?? []).map((p, i) => ({ d: i, v: p.total_value_usd }));
  // `total_return_pct` is portfolio return relative to the initial seed cash
  // — paper trading's natural "delta vs start", since net-worth-style "vs
  // 30 days ago" doesn't make sense here.
  const returnPct = portfolio?.total_return_pct ?? null;
  const tone = returnPct == null ? "neutral" : returnPct >= 0 ? "up" : "down";

  // Display primary in the user's base currency (Goals convention) when
  // it differs from USD; otherwise just USD.
  const primaryDisplay =
    portfolio == null
      ? ""
      : baseCurrency !== "USD" && usdToBase != null
      ? formatMoney(portfolio.total_value_usd * usdToBase, baseCurrency, { maximumFractionDigits: 0 })
      : formatMoney(portfolio.total_value_usd, "USD");
  const showNativeSubline =
    portfolio != null && baseCurrency !== "USD" && usdToBase != null;

  return (
    <section className="rounded-xl border border-border bg-surface p-md shadow-card">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-uppercase-label uppercase text-text-muted">Portfolio value</h3>
        {tone === "up" && <TrendingUp className="h-4 w-4 text-success" />}
        {tone === "down" && <TrendingDown className="h-4 w-4 text-danger" />}
      </div>

      {portfolioQuery.isLoading ? (
        <Skeleton lines={2} />
      ) : portfolioQuery.isError || portfolio == null ? (
        <Hint>Portfolio unavailable.</Hint>
      ) : (
        <>
          <div className="text-h3 font-semibold tabular text-text-primary">
            {primaryDisplay}
          </div>
          {showNativeSubline && (
            <div className="mb-1 text-uppercase-label uppercase text-text-muted tabular">
              {formatMoney(portfolio.total_value_usd, "USD")}
            </div>
          )}
          <div
            className={cn(
              "mb-3 text-body-small tabular",
              tone === "up" && "text-success",
              tone === "down" && "text-danger",
              tone === "neutral" && "text-text-muted",
            )}
          >
            {returnPct != null ? (
              <>{returnPct >= 0 ? "+" : ""}{returnPct.toFixed(2)}% all-time return</>
            ) : (
              <>No return data yet</>
            )}
          </div>
          {sparkData.length >= 2 ? (
            <div className="h-12">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={sparkData}>
                  <defs>
                    <linearGradient id="ip-pf" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="rgb(79 70 229)" stopOpacity={0.4} />
                      <stop offset="100%" stopColor="rgb(79 70 229)" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <Area
                    type="monotone"
                    dataKey="v"
                    stroke="rgb(79 70 229)"
                    strokeWidth={2}
                    fill="url(#ip-pf)"
                    isAnimationActive={false}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          ) : null}
        </>
      )}
    </section>
  );
}


// ---------------------------------------------------------------------------
// Upcoming planned payments (next 3 by next_due)
// ---------------------------------------------------------------------------

function UpcomingCard() {
  const baseCurrency = useCurrency();
  const recurringQuery = useQuery({
    queryKey: qk.recurring.all(),
    queryFn: recApi.listRecurring,
  });

  const upcoming = useMemo(() => {
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    return (recurringQuery.data ?? [])
      .filter((r) => new Date(r.next_due) >= today)
      .sort((a, b) => new Date(a.next_due).getTime() - new Date(b.next_due).getTime())
      .slice(0, 3);
  }, [recurringQuery.data]);

  return (
    <Card title="Coming up" actionTo="/planned" actionLabel="All">
      {recurringQuery.isLoading ? (
        <Skeleton lines={3} />
      ) : recurringQuery.isError ? (
        <Hint>Couldn't load planned payments.</Hint>
      ) : upcoming.length === 0 ? (
        <Hint>No upcoming planned payments.</Hint>
      ) : (
        <ul className="space-y-2">
          {upcoming.map((p) => (
            <li
              key={p.id}
              className="flex items-center justify-between gap-md text-body-small"
            >
              <div className="min-w-0 flex-1">
                <div className="truncate font-medium text-text-primary">{p.name}</div>
                <div className="text-text-muted">
                  {new Date(p.next_due).toLocaleDateString("en-US", {
                    month: "short", day: "numeric",
                  })}
                </div>
              </div>
              <div className="text-right">
                <div
                  className={cn(
                    "tabular font-medium",
                    p.is_income ? "text-success" : "text-danger",
                  )}
                >
                  {p.is_income ? "+" : "−"}
                  {p.amount_base != null
                    ? formatMoney(p.amount_base, baseCurrency)
                    : formatMoney(p.amount, p.currency)}
                </div>
                {p.currency !== baseCurrency && p.amount_base != null && (
                  <div className="text-uppercase-label uppercase text-text-muted tabular">
                    {p.is_income ? "+" : "−"}
                    {formatMoney(p.amount, p.currency)}
                  </div>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}


// ---------------------------------------------------------------------------
// Budgets near limit — top 3 categories where (spent / monthly_budget) ≥ 80%
// for the current month. Friendly empty state when no budget is near full.
// ---------------------------------------------------------------------------

function BudgetsNearLimitCard() {
  const baseCurrency = useCurrency();
  // Month bounds — same shape the Budget page uses to scope its spending query.
  const { start, end } = useMemo(() => {
    const now = new Date();
    const startStr = new Date(now.getFullYear(), now.getMonth(), 1).toISOString().slice(0, 10);
    const endStr = new Date(now.getFullYear(), now.getMonth() + 1, 0).toISOString().slice(0, 10);
    return { start: startStr, end: endStr };
  }, []);

  const categoriesQuery = useQuery({
    queryKey: qk.categories.all(),
    queryFn: catApi.listCategories,
  });
  const spendingQuery = useQuery({
    queryKey: qk.reports.spending(start, end),
    queryFn: () => reportsApi.getSpendingReport(start, end),
  });

  const nearLimit = useMemo(() => {
    const cats = categoriesQuery.data ?? [];
    const items = spendingQuery.data?.items ?? [];
    const spentByCatId = new Map<string, number>();
    for (const it of items) {
      if (it.category_id) spentByCatId.set(it.category_id, it.total);
    }
    return cats
      .filter((c) => c.monthly_budget > 0)
      .map((c) => {
        const spent = spentByCatId.get(c.id) ?? 0;
        const pct = spent / c.monthly_budget;
        return { id: c.id, name: c.name, budget: c.monthly_budget, spent, pct };
      })
      .filter((r) => r.pct >= 0.8)
      .sort((a, b) => b.pct - a.pct)
      .slice(0, 3);
  }, [categoriesQuery.data, spendingQuery.data]);

  const isLoading = categoriesQuery.isLoading || spendingQuery.isLoading;
  const isError = categoriesQuery.isError || spendingQuery.isError;

  return (
    <Card title="Budgets near limit" actionTo="/budget" actionLabel="All">
      {isLoading ? (
        <Skeleton lines={3} />
      ) : isError ? (
        <Hint>Budgets unavailable.</Hint>
      ) : nearLimit.length === 0 ? (
        <Hint>All budgets comfortably under 80% — nothing to flag.</Hint>
      ) : (
        <ul className="space-y-2">
          {nearLimit.map((r) => {
            const over = r.pct >= 1;
            const pctDisplay = Math.round(r.pct * 100);
            return (
              <li key={r.id} className="space-y-1 text-body-small">
                <div className="flex items-center justify-between gap-md">
                  <span className="truncate font-medium text-text-primary">{r.name}</span>
                  <span
                    className={cn(
                      "tabular font-medium",
                      over ? "text-danger" : "text-warning-700",
                    )}
                  >
                    {pctDisplay}%
                  </span>
                </div>
                <div className="text-uppercase-label uppercase text-text-muted tabular">
                  {formatMoney(r.spent, baseCurrency, { maximumFractionDigits: 0 })}
                  {" / "}
                  {formatMoney(r.budget, baseCurrency, { maximumFractionDigits: 0 })}
                </div>
                <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-soft">
                  <div
                    className={cn(
                      "h-full rounded-full transition-all",
                      over ? "bg-danger" : "bg-warning",
                    )}
                    style={{ width: `${Math.min(100, pctDisplay)}%` }}
                  />
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}


// ---------------------------------------------------------------------------
// Tiny shared bits
// ---------------------------------------------------------------------------

function Card({
  title, actionTo, actionLabel, children,
}: {
  title: string;
  actionTo: string;
  actionLabel: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-xl border border-border bg-surface p-md shadow-card">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-uppercase-label uppercase text-text-muted">{title}</h3>
        <Link
          to={actionTo}
          className="text-body-small text-primary transition-colors hover:text-primary-hover focus-ring rounded"
        >
          {actionLabel}
        </Link>
      </div>
      {children}
    </section>
  );
}

function Hint({ children }: { children: React.ReactNode }) {
  return <p className="text-body-small text-text-muted">{children}</p>;
}

function Skeleton({ lines = 2 }: { lines?: number }) {
  return (
    <div className="space-y-2">
      {Array.from({ length: lines }).map((_, i) => (
        <div key={i} className="h-3 w-full animate-pulse rounded bg-surface-variant" />
      ))}
      <div className="flex items-center gap-2 pt-1 text-body-small text-text-muted">
        <Loader2 className="h-3 w-3 animate-spin" /> Loading…
      </div>
    </div>
  );
}
