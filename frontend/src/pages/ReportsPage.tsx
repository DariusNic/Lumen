import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  Legend,
  Line,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Loader2, Printer } from "lucide-react";
import { Button } from "@/components/ui/button";
import { SectionCard } from "@/components/shared/SectionCard";
import { MonthPicker, type YearMonth } from "@/components/shared/MonthPicker";
import { useCurrency } from "@/hooks/useCurrency";
import { formatMoney } from "@/lib/format";
import { qk } from "@/lib/queryKeys";
import { parseApiError } from "@/api/client";
import { cn } from "@/lib/utils";
import * as reportsApi from "@/api/reports.api";
import * as nwApi from "@/api/networth.api";

const MONTH_LABELS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

// Stable palette for the category breakdown — re-derive a color from the
// name so charts stay consistent across renders even when the API doesn't
// return a category color.
const PALETTE = [
  "rgb(244 63 94)", "rgb(79 70 229)", "rgb(16 185 129)", "rgb(6 182 212)",
  "rgb(245 158 11)", "rgb(168 85 247)", "rgb(20 184 166)", "rgb(148 163 184)",
  "rgb(14 165 233)", "rgb(236 72 153)", "rgb(99 102 241)", "rgb(34 197 94)",
];

function colorFor(name: string): string {
  let hash = 0;
  for (let i = 0; i < name.length; i++) hash = (hash * 31 + name.charCodeAt(i)) >>> 0;
  return PALETTE[hash % PALETTE.length];
}

// Scope drives every query on the page. "all" = lifetime / 13-rolling-month
// view; "year" = a calendar year; "month" = a single month, with the
// 13-month trend charts re-anchored to end at that month.
type Scope = "all" | "year" | "month";

function isoDateLocal(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export default function ReportsPage() {
  const currency = useCurrency();
  const now = new Date();

  const [scope, setScope] = useState<Scope>("all");
  const [year, setYear] = useState<number>(now.getFullYear());
  const [month, setMonth] = useState<YearMonth>(MonthPicker.thisMonth());

  // `from` / `to` are the date-range bounds for the all-time aggregations
  // (Category breakdown + Top merchants).
  // `monthlyEnd` is the `end=YYYY-MM` anchor for the rolling 13-month chart
  // queries — when scope=year we send "<year>-12" + months=12 so the
  // chart shows that year only.
  const { from, to, monthlyEnd, monthlyCount } = useMemo(() => {
    if (scope === "all") {
      return { from: undefined, to: undefined, monthlyEnd: undefined, monthlyCount: 13 };
    }
    if (scope === "year") {
      return {
        from: `${year}-01-01`,
        to: `${year}-12-31`,
        monthlyEnd: `${year}-12`,
        monthlyCount: 12,
      };
    }
    // month
    const f = new Date(month.year, month.month - 1, 1);
    const t = new Date(month.year, month.month, 0);
    const mm = String(month.month).padStart(2, "0");
    return {
      from: isoDateLocal(f),
      to: isoDateLocal(t),
      monthlyEnd: `${month.year}-${mm}`,
      monthlyCount: 13,
    };
  }, [scope, year, month]);

  const scopeLabel = useMemo(() => {
    if (scope === "all") return "all time";
    if (scope === "year") return `${year}`;
    return `${MONTH_LABELS[month.month - 1]} ${month.year}`;
  }, [scope, year, month]);

  // 13-month rolling charts (or 12 months of selected year). Anchored via
  // the `end=YYYY-MM` query param when scope is not "all".
  const monthlyQuery = useQuery({
    queryKey: qk.reports.monthly(monthlyCount, monthlyEnd),
    queryFn: () => reportsApi.getMonthlyReport(monthlyCount, monthlyEnd),
  });
  const spendingQuery = useQuery({
    queryKey: qk.reports.spending(from, to),
    queryFn: () => reportsApi.getSpendingReport(from, to),
  });
  const merchantsQuery = useQuery({
    queryKey: qk.reports.merchants(from, to, 10),
    queryFn: () => reportsApi.getTopMerchants(from, to, 10),
  });
  // Net worth API only takes a range bucket; the 1Y window is the widest
  // available reasonable default. We then filter client-side per scope.
  const networthQuery = useQuery({
    queryKey: qk.networth.history("1Y"),
    queryFn: () => nwApi.getHistory("1Y"),
  });
  // Live current net worth — used to ANCHOR the historical snapshot
  // chart so its right edge matches the live value the user sees on
  // the Dashboard. Snapshots can drift (mixed-currency rows, stale
  // by up to a day) and would otherwise contradict the Dashboard's
  // headline number.
  const networthCurrentQuery = useQuery({
    queryKey: qk.networth.current(),
    queryFn: nwApi.getCurrent,
  });

  const isLoading =
    monthlyQuery.isLoading ||
    spendingQuery.isLoading ||
    merchantsQuery.isLoading ||
    networthQuery.isLoading ||
    networthCurrentQuery.isLoading;

  const firstError =
    monthlyQuery.error ?? spendingQuery.error ?? merchantsQuery.error ?? networthQuery.error ?? networthCurrentQuery.error;

  // -------------------------------------------------------------------------
  // Derived datasets
  // -------------------------------------------------------------------------
  const monthly = monthlyQuery.data?.months ?? [];

  const monthlySpend = useMemo(
    () =>
      monthly.map((m) => ({
        month: `${MONTH_LABELS[m.month - 1]} '${String(m.year).slice(2)}`,
        spent: m.expense,
      })),
    [monthly],
  );
  const incomeVs = useMemo(
    () =>
      monthly.map((m) => ({
        month: `${MONTH_LABELS[m.month - 1]} '${String(m.year).slice(2)}`,
        income: m.income,
        expenses: m.expense,
      })),
    [monthly],
  );

  const spendStats = useMemo(() => {
    if (!monthlySpend.length) return { avg: 0, hi: null as null | typeof monthlySpend[0], lo: null as null | typeof monthlySpend[0] };
    const avg = monthlySpend.reduce((s, r) => s + r.spent, 0) / monthlySpend.length;
    const sorted = [...monthlySpend].sort((a, b) => b.spent - a.spent);
    return { avg, hi: sorted[0], lo: sorted[sorted.length - 1] };
  }, [monthlySpend]);

  // Category breakdown is a donut. Goal contributions used to be
  // filtered out here (treated as savings, not spending) but Budget /
  // Dashboard / Top merchants all count them, so excluding them ONLY
  // on this donut produced a cross-page inconsistency. We now include
  // every category — the goal-contribution slice can dominate the
  // chart on heavy-savings months, which is honest reporting of where
  // the user's money went.
  const categories = useMemo(() => {
    const items = spendingQuery.data?.items ?? [];
    const total = items.reduce((s, c) => s + c.total, 0);
    return items.map((c) => ({
      name: c.category_name,
      value: c.total,
      pct: total > 0 ? (c.total / total) * 100 : 0,
      fill: c.color || colorFor(c.category_name),
    }));
  }, [spendingQuery.data]);
  const totalCat = categories.reduce((s, c) => s + c.value, 0);

  // When one category dominates (Goals at 95% is common), the remaining
  // sub-1% slices render as sub-pixel arcs and look like the donut is
  // missing them entirely. Inflate any slice below MIN_DISPLAY_PCT for the
  // chart only — keep the original `value` field so the tooltip and the
  // side legend still report the truth.
  const MIN_DISPLAY_PCT = 0.5; // ≈ 1.8° of arc, the smallest visible slice.
  const categoriesForChart = useMemo(() => {
    if (totalCat === 0) return categories;
    const floor = (MIN_DISPLAY_PCT / 100) * totalCat;
    return categories.map((c) => ({
      ...c,
      chartValue: Math.max(c.value, floor),
    }));
  }, [categories, totalCat]);

  const merchants = merchantsQuery.data?.items ?? [];

  // Net worth: filter the 1Y daily series client-side per scope, then add a
  // sparse-tick formatter so only month boundaries label the X axis.
  //
  // The snapshot rows in `net_worth_snapshots` store the value in
  // whatever base currency was active when the snapshot was taken —
  // switching base later doesn't re-convert historical rows. So the raw
  // series can land at a number different from the LIVE net worth that
  // the Dashboard shows. To keep the two pages consistent, we shift the
  // entire series by `live_current_net_worth - last_snapshot_value` so
  // the rightmost data point matches the Dashboard headline. The
  // shape (relative trend) is preserved; only the vertical offset
  // changes.
  const networth = useMemo(() => {
    const points = networthQuery.data?.points ?? [];
    const filtered = points.filter((p) => {
      const d = new Date(p.date);
      if (scope === "year") return d.getFullYear() === year;
      if (scope === "month") return d.getFullYear() === month.year && d.getMonth() + 1 === month.month;
      return true;
    });
    const live = networthCurrentQuery.data?.net_worth;
    const lastSnapshot = filtered.length > 0 ? filtered[filtered.length - 1].net_worth : null;
    const shift =
      live != null && lastSnapshot != null
        ? live - lastSnapshot
        : 0;
    return filtered.map((p, i, arr) => {
      const date = new Date(p.date);
      const prev = i > 0 ? new Date(arr[i - 1].date) : null;
      const monthRolled = !prev || prev.getMonth() !== date.getMonth();
      return {
        iso: isoDateLocal(date),
        axis:
          monthRolled || i === arr.length - 1
            ? date.toLocaleDateString("en-GB", { month: "short", year: "2-digit" })
            : "",
        net: p.net_worth + shift,
      };
    });
  }, [networthQuery.data, networthCurrentQuery.data, scope, year, month]);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center gap-2 py-2xl text-body-small text-text-muted">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading reports…
      </div>
    );
  }

  if (firstError) {
    return (
      <SectionCard title="Reports">
        <p className="text-body-small text-danger">{parseApiError(firstError)}</p>
      </SectionCard>
    );
  }

  const hasMonthly = monthlySpend.length > 0;
  const hasCategories = categories.length > 0;
  const hasMerchants = merchants.length > 0;
  const hasNetWorth = networth.length > 1;

  const minYear = now.getFullYear() - 5;
  const maxYear = now.getFullYear();

  // Trend chart description tweaks per scope, so the user always knows what
  // window they're looking at.
  const trendWindowLabel =
    scope === "year"
      ? `${year} (Jan – Dec)`
      : scope === "month"
        ? `13 months ending ${MONTH_LABELS[month.month - 1]} ${month.year}`
        : "rolling last 13 months";

  return (
    <div className="space-y-lg animate-fade-in print-area">
      <header className="flex flex-wrap items-center justify-between gap-md no-print">
        <div>
          <h1 className="text-h2 font-h2 text-text-primary">Reports</h1>
          <p className="text-body-small text-text-muted">
            Base currency {currency}
          </p>
        </div>
        <Button variant="primary" onClick={() => window.print()}>
          <Printer className="h-4 w-4" /> Print
        </Button>
      </header>

      {/* Print-only header — gives the printed report a self-contained
          title (the regular header above is hidden in print to drop the
          Print button itself). */}
      <header className="hidden print-only mb-4">
        <h1 className="text-2xl font-bold">Financial Reports</h1>
        <p className="text-sm text-text-muted">
          Base currency {currency} · Scope: {scopeLabel} · Generated{" "}
          {now.toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" })}
        </p>
      </header>

      {/* === Scope selector (TOP of page, applies to every section below) ===
          Entire card is `no-print` — the print-only header above already
          surfaces the active scope ("Scope: <scopeLabel>"), so this card
          would be redundant chrome on paper. */}
      <SectionCard
        className="no-print"
        title="Data range"
        description="Filters every section on this page"
      >
        <div className="flex flex-wrap items-center gap-3 no-print">
          <div className="inline-flex rounded-lg border border-border bg-surface p-0.5">
            {(["all", "year", "month"] as const).map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => setScope(s)}
                className={cn(
                  "rounded-md px-3 py-1 text-body-small transition-colors",
                  scope === s
                    ? "bg-primary text-on-primary font-semibold"
                    : "text-text-muted hover:bg-surface-soft",
                )}
              >
                {s === "all" ? "All time" : s === "year" ? "Year" : "Month"}
              </button>
            ))}
          </div>
          {scope === "year" && (
            <div className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-surface p-0.5">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setYear((y) => Math.max(minYear, y - 1))}
                disabled={year <= minYear}
              >
                ‹
              </Button>
              <span className="px-2 text-body-small font-semibold tabular">{year}</span>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setYear((y) => Math.min(maxYear, y + 1))}
                disabled={year >= maxYear}
              >
                ›
              </Button>
            </div>
          )}
          {scope === "month" && <MonthPicker value={month} onChange={setMonth} />}
        </div>
        <p className="mt-2 text-uppercase-label uppercase text-text-muted">
          Showing data for: {scopeLabel}
        </p>
      </SectionCard>

      {/* 1. Spending over time */}
      <SectionCard
        title="Spending over time"
        description={`Total monthly spending — ${trendWindowLabel}`}
      >
        {!hasMonthly ? (
          <p className="py-md text-body-small text-text-muted">
            No transactions in this window.
          </p>
        ) : (
          <>
            <div className="h-[280px]">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={monthlySpend}>
                  <CartesianGrid stroke="rgb(var(--border))" strokeDasharray="3 3" vertical={false} />
                  <XAxis
                    dataKey="month"
                    axisLine={false}
                    tickLine={false}
                    tick={{ fontSize: 12, fill: "rgb(var(--text-muted))" }}
                  />
                  <YAxis hide />
                  <Tooltip
                    cursor={{ fill: "rgb(var(--surface-soft))" }}
                    formatter={(v: number) => formatMoney(v, currency)}
                    contentStyle={{
                      borderRadius: 8,
                      border: "1px solid rgb(var(--border))",
                      fontSize: 12,
                    }}
                  />
                  <Bar dataKey="spent" fill="rgb(79 70 229)" radius={[6, 6, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="mt-3 grid grid-cols-3 gap-3 border-t border-border pt-3 text-body-small">
              <Stat label="Average / month" value={formatMoney(spendStats.avg, currency)} />
              <Stat
                label="Highest"
                value={
                  spendStats.hi
                    ? `${formatMoney(spendStats.hi.spent, currency)} · ${spendStats.hi.month}`
                    : "—"
                }
              />
              <Stat
                label="Lowest"
                value={
                  spendStats.lo
                    ? `${formatMoney(spendStats.lo.spent, currency)} · ${spendStats.lo.month}`
                    : "—"
                }
              />
            </div>
          </>
        )}
      </SectionCard>

      {/* 2. Income vs expenses */}
      <SectionCard
        title="Income vs expenses"
        description={`Side-by-side monthly totals — ${trendWindowLabel}`}
        contentClassName={hasMonthly ? "h-[300px]" : undefined}
      >
        {!hasMonthly ? (
          <p className="py-md text-body-small text-text-muted">
            Need at least one month of activity in this window.
          </p>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={incomeVs}>
              <CartesianGrid stroke="rgb(var(--border))" strokeDasharray="3 3" vertical={false} />
              <XAxis
                dataKey="month"
                axisLine={false}
                tickLine={false}
                tick={{ fontSize: 12, fill: "rgb(var(--text-muted))" }}
              />
              <YAxis
                axisLine={false}
                tickLine={false}
                tick={{ fontSize: 11, fill: "rgb(var(--text-muted))" }}
                tickFormatter={(v) => `${(v / 1000).toFixed(0)}k`}
              />
              <Tooltip
                contentStyle={{
                  borderRadius: 8,
                  border: "1px solid rgb(var(--border))",
                  fontSize: 12,
                }}
                formatter={(v: number, name) => [formatMoney(v, currency), name]}
              />
              <Legend
                verticalAlign="top"
                height={28}
                iconType="circle"
                wrapperStyle={{ fontSize: 12 }}
                formatter={(value) => (value === "income" ? "Income" : "Expenses")}
              />
              <Bar dataKey="income" fill="rgb(16 185 129)" radius={[4, 4, 0, 0]} />
              <Bar dataKey="expenses" fill="rgb(239 68 68)" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        )}
      </SectionCard>

      {/* 3. Category breakdown — DONUT chart so every category stays visible
             even when one dominates. Side legend lists each slice with
             amount + % for the precise number. */}
      <SectionCard
        title="Category breakdown"
        description={`Total spending per category — ${scopeLabel}`}
      >
        {!hasCategories ? (
          <p className="py-md text-body-small text-text-muted">
            No spending recorded in the selected range.
          </p>
        ) : (
          <div className="grid gap-md md:grid-cols-[260px_1fr]">
            <div className="h-[260px]">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={categoriesForChart}
                    // `chartValue` is the inflated-for-display field; `value`
                    // remains the truth that the tooltip pulls from below.
                    // `paddingAngle=0` mirrors the Dashboard donut fix — gaps
                    // were eating tiny slices into invisibility.
                    dataKey="chartValue"
                    nameKey="name"
                    innerRadius={60}
                    outerRadius={100}
                    paddingAngle={0}
                    isAnimationActive={false}
                  >
                    {categoriesForChart.map((c, i) => (
                      <Cell key={i} fill={c.fill} stroke="rgb(var(--surface))" strokeWidth={2} />
                    ))}
                  </Pie>
                  <Tooltip
                    formatter={(_v: number, _name, item) => [
                      `${formatMoney(item?.payload?.value ?? 0, currency)} · ${item?.payload?.pct?.toFixed(2)}%`,
                      item?.payload?.name,
                    ]}
                    contentStyle={{
                      borderRadius: 8,
                      border: "1px solid rgb(var(--border))",
                      fontSize: 12,
                    }}
                  />
                </PieChart>
              </ResponsiveContainer>
            </div>
            <ul className="grid content-start gap-2 self-center">
              {categories.map((c) => (
                <li
                  key={c.name}
                  className="grid grid-cols-[12px_1fr_auto] items-center gap-3 text-body-small"
                >
                  <span
                    aria-hidden="true"
                    className="h-3 w-3 rounded-sm"
                    style={{ backgroundColor: c.fill }}
                  />
                  <span className="truncate font-medium text-text-primary">{c.name}</span>
                  <span className="tabular tabular-nums text-text-muted">
                    <span className="font-semibold text-text-primary">
                      {formatMoney(c.value, currency)}
                    </span>{" "}
                    {/* Show 2 decimals when the slice is below 1% so categories
                        that contribute 0.05% don't all collapse to "0%". */}
                    · {c.pct < 1 ? c.pct.toFixed(2) : c.pct.toFixed(0)}%
                  </span>
                </li>
              ))}
              <li className="mt-1 grid grid-cols-[12px_1fr_auto] items-center gap-3 border-t border-border pt-2 text-body-small">
                <span aria-hidden="true" />
                <span className="font-semibold uppercase text-uppercase-label text-text-muted">
                  Total
                </span>
                <span className="font-semibold tabular tabular-nums">
                  {formatMoney(totalCat, currency)}
                </span>
              </li>
            </ul>
          </div>
        )}
      </SectionCard>

      {/* 4. Top merchants */}
      <SectionCard
        title="Top merchants"
        description={`Sorted by total spend — ${scopeLabel}`}
        noPadding
      >
        {!hasMerchants ? (
          <p className="px-md py-md text-body-small text-text-muted">
            No merchant data in the selected range.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-body-small">
              <thead>
                <tr className="border-b border-border text-uppercase-label uppercase text-text-muted">
                  <th className="px-md py-3 text-left font-medium">Merchant</th>
                  <th className="px-md py-3 text-left font-medium">Category</th>
                  <th className="px-md py-3 text-right font-medium">Count</th>
                  <th className="px-md py-3 text-right font-medium">Avg</th>
                  <th className="px-md py-3 text-right font-medium">Total</th>
                </tr>
              </thead>
              <tbody>
                {merchants.map((m) => (
                  <tr
                    key={m.merchant}
                    className="border-b border-border/60 transition-colors hover:bg-surface-soft last:border-0"
                  >
                    <td className="px-md py-3 font-medium">{m.merchant}</td>
                    <td className="px-md py-3 text-text-muted">{m.category_name}</td>
                    <td className="px-md py-3 text-right tabular">{m.count}</td>
                    <td className="px-md py-3 text-right tabular">
                      {formatMoney(m.avg, currency)}
                    </td>
                    <td className="px-md py-3 text-right tabular font-semibold">
                      {formatMoney(m.total, currency)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </SectionCard>

      {/* 5. Net worth evolution */}
      <SectionCard
        title="Net worth evolution"
        description={`Daily snapshots — ${scopeLabel}`}
        contentClassName={hasNetWorth ? "h-[260px]" : undefined}
      >
        {!hasNetWorth ? (
          <p className="py-md text-body-small text-text-muted">
            Net-worth history appears once a few daily snapshots have been recorded for the selected range.
          </p>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={networth}>
              <CartesianGrid stroke="rgb(var(--border))" strokeDasharray="3 3" vertical={false} />
              <XAxis
                dataKey="axis"
                interval={0}
                axisLine={false}
                tickLine={false}
                tick={{ fontSize: 11, fill: "rgb(var(--text-muted))" }}
              />
              <YAxis
                axisLine={false}
                tickLine={false}
                tick={{ fontSize: 11, fill: "rgb(var(--text-muted))" }}
                tickFormatter={(v) => `${(v / 1000).toFixed(0)}k`}
              />
              <Tooltip
                cursor={{ stroke: "rgb(var(--border))", strokeWidth: 1 }}
                contentStyle={{
                  borderRadius: 8,
                  border: "1px solid rgb(var(--border))",
                  fontSize: 12,
                }}
                labelFormatter={(_label, payload) => {
                  const iso = payload?.[0]?.payload?.iso;
                  if (!iso) return "";
                  return new Date(iso).toLocaleDateString("en-GB", {
                    day: "numeric", month: "short", year: "numeric",
                  });
                }}
                formatter={(v: number) => formatMoney(v, currency)}
              />
              <Line
                type="monotone"
                dataKey="net"
                stroke="rgb(79 70 229)"
                strokeWidth={2.5}
                dot={false}
                activeDot={{ r: 4 }}
                isAnimationActive={false}
              />
            </ComposedChart>
          </ResponsiveContainer>
        )}
      </SectionCard>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-uppercase-label uppercase text-text-muted">{label}</div>
      <div className="font-semibold tabular text-text-primary">{value}</div>
    </div>
  );
}
