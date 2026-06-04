import { useQuery } from "@tanstack/react-query";
import {
  Area,
  AreaChart,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { ArrowRight, Plus, TrendingDown, TrendingUp, Wallet } from "lucide-react";
import { Link } from "react-router-dom";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { GoalAmountDisplay } from "@/components/goals/GoalAmountDisplay";
import { KpiCard } from "@/components/shared/KpiCard";
import { MonthPicker, type YearMonth } from "@/components/shared/MonthPicker";
import { SectionCard } from "@/components/shared/SectionCard";
import { useCurrency } from "@/hooks/useCurrency";
import { useAuthStore } from "@/store/authStore";
import { formatMoney } from "@/lib/format";
import { qk } from "@/lib/queryKeys";
import { cn } from "@/lib/utils";
import * as accountsApi from "@/api/accounts.api";
import * as goalsApi from "@/api/goals.api";
import * as recApi from "@/api/recurring.api";
import * as reportsApi from "@/api/reports.api";
import * as txApi from "@/api/transactions.api";

const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

function boundsFor(ym: YearMonth) {
  const start = new Date(ym.year, ym.month - 1, 1).toISOString().slice(0, 10);
  const end = new Date(ym.year, ym.month, 0).toISOString().slice(0, 10);
  return { start, end };
}

export default function DashboardPage() {
  const currency = useCurrency();
  const userName = useAuthStore((s) => s.user?.full_name?.split(" ")[0] ?? "");
  const hour = new Date().getHours();
  const greet = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";

  // Single source of truth for "which month am I looking at?". Drives every
  // card whose label reads "this month" — KPIs, donut, top drains. Net Worth +
  // Total Balance are inherently all-time and ignore the picker.
  const [selectedMonth, setSelectedMonth] = useState<YearMonth>(MonthPicker.thisMonth());
  const { start, end } = boundsFor(selectedMonth);
  const isCurrentMonth =
    selectedMonth.year === new Date().getFullYear() &&
    selectedMonth.month === new Date().getMonth() + 1;
  const monthHeading = `${MONTH_NAMES[selectedMonth.month - 1]} ${selectedMonth.year}`;

  const accountsQuery = useQuery({ queryKey: qk.accounts.all(), queryFn: accountsApi.listAccounts });
  const spendingQuery = useQuery({
    queryKey: qk.reports.spending(start, end),
    queryFn: () => reportsApi.getSpendingReport(start, end),
  });
  // KPI mini-charts show the 6 months ending at the user-selected month
  // (inclusive). "end" is the YYYY-MM string the backend uses to anchor
  // the window. So picking March 2026 returns Oct 2025 → Mar 2026.
  const monthlyEnd = `${selectedMonth.year}-${String(selectedMonth.month).padStart(2, "0")}`;
  const monthlyQuery = useQuery({
    queryKey: qk.reports.monthly(6, monthlyEnd),
    queryFn: () => reportsApi.getMonthlyReport(6, monthlyEnd),
  });
  const goalsQuery = useQuery({ queryKey: qk.goals.all(), queryFn: goalsApi.listGoals });
  const recurringQuery = useQuery({ queryKey: qk.recurring.all(), queryFn: recApi.listRecurring });
  const recentTxQuery = useQuery({
    queryKey: qk.transactions.list({ page: 1, page_size: 5 }),
    queryFn: () => txApi.listTransactions({ page: 1, page_size: 5 }),
  });
  const totals = accountsQuery.data?.totals;
  const months = monthlyQuery.data?.months ?? [];
  const now = new Date();
  // The "selected" month's row in the monthly report (if it exists in the
  // trailing-6 window). For older selections we fall back to the spending
  // report's totals so the KPIs always reflect the picker.
  const selectedRow = months.find(
    (m) => m.year === selectedMonth.year && m.month === selectedMonth.month,
  );
  const selectedIncome =
    selectedRow?.income ?? spendingQuery.data?.total_income ?? 0;
  const selectedExpense =
    selectedRow?.expense ?? spendingQuery.data?.total_expense ?? 0;
  // Compare against the month immediately preceding the selection.
  const prevYM = ((y: number, m: number) =>
    m === 1 ? { year: y - 1, month: 12 } : { year: y, month: m - 1 })(
    selectedMonth.year,
    selectedMonth.month,
  );
  const prevRow = months.find(
    (m) => m.year === prevYM.year && m.month === prevYM.month,
  );

  // "Total balance" = liquid spendable money: manual cash + savings accounts
  // PLUS the auto-tracked Net cash flow account (running sum of all your
  // imported / added transactions). Without the Net cash flow piece this
  // would always read 0 for users who only import bank CSVs.
  const accounts = accountsQuery.data?.accounts ?? [];
  const cashSavings = accounts
    .filter((a) => a.category === "asset" && (a.type === "cash" || a.type === "savings"))
    .reduce((s, a) => s + a.balance, 0);
  const netCashFlow =
    accounts.find((a) => a.source_ref === "transactions:net")?.balance ?? 0;
  const totalBalance = cashSavings + netCashFlow;

  const incomeDelta =
    prevRow && prevRow.income
      ? (selectedIncome - prevRow.income) / prevRow.income
      : null;
  const expenseDelta =
    prevRow && prevRow.expense
      ? (selectedExpense - prevRow.expense) / prevRow.expense
      : null;

  // Honest sparklines: real values from the monthly report (income/expense)
  // plus a cumulative running balance for "Total balance". Net worth's
  // sparkline now comes from the real net_worth_snapshots history; if the
  // user has no snapshots yet (fresh account) we fall back to the running
  // balance so the card is never blank.
  // KpiCard mini-chart points are `{label, value}` — label drives the X-axis
  // tick + hover tooltip header, value drives the curve + Y-axis.
  const monthLabel = (m: { year: number; month: number }) =>
    `${MONTH_NAMES[m.month - 1].slice(0, 3)} ${String(m.year).slice(-2)}`;
  const incomeSpark = months.map((m) => ({ label: monthLabel(m), value: m.income }));
  const expenseSpark = months.map((m) => ({ label: monthLabel(m), value: m.expense }));
  const balanceSpark: { label: string; value: number }[] = [];
  let running = 0;
  for (const m of months) {
    running += m.income - m.expense;
    balanceSpark.push({ label: monthLabel(m), value: running });
  }
  // Net worth chart: take the synthetic running-balance series (cumulative
  // income − expense per month, computed from `amount_base` so it's
  // always in the user's current base currency) and SHIFT it so the
  // rightmost point equals the live net worth shown in the headline.
  //
  // Why a shift instead of using the raw running balance:
  //   - The headline ("NET WORTH" = `totals.net_worth`) includes Paper
  //     Portfolio + manual accounts + Net cash flow MINUS liabilities,
  //     summed live from `/api/accounts`. It's a snapshot of "right now".
  //   - `balanceSpark` only tracks cash-flow accumulation. By itself it
  //     ends at a different number than the headline, which looks broken
  //     ("headline says −RON 649k, chart says −RON 12k for the same day").
  //   - We don't have a reliable per-day historical net worth series
  //     (snapshot history is in mixed currencies — see the Dec 25
  //     migration drift). So we take the only consistent trend we DO
  //     have (cash flow shape) and offset it vertically so the present
  //     value lines up. The shape conveys "are you accumulating or
  //     burning cash month over month"; the absolute scale honours the
  //     headline number the user just read above.
  //   - Assumption: accounts/portfolio/liabilities held constant over
  //     the window. Not literally true, but the cash-flow trend is the
  //     only signal we can trust per month — and a chart that lands at
  //     the right value beats one that ends at a meaningless number.
  const liveNetWorth = totals?.net_worth ?? 0;
  const lastBalance = balanceSpark.length > 0 ? balanceSpark[balanceSpark.length - 1].value : 0;
  const netWorthShift = liveNetWorth - lastBalance;
  const netWorthSpark = balanceSpark.map((p) => ({
    label: p.label,
    value: p.value + netWorthShift,
  }));
  const moneyFmt = (v: number) =>
    formatMoney(v, currency, { maximumFractionDigits: 0 });

  // Include every category — Goals contributions are stored as negative
  // transactions in the unified ledger, and Budget / Reports / Top
  // merchants all count them as spending, so the Dashboard donut should
  // too. Caveat: a heavy contribution month can let the Goals slice
  // dominate the chart visually; that's honest reporting of where the
  // money actually went.
  const spendingItems = spendingQuery.data?.items ?? [];
  const totalExpense = spendingItems.reduce((s, it) => s + it.total, 0);
  const donutData = spendingItems.map((it) => ({
    name: it.category_name,
    value: it.total,
    // Round to 1 decimal so the legend reads "41.6%" rather than
    // `41.65595195…`.
    pct: totalExpense > 0 ? Math.round((it.total / totalExpense) * 1000) / 10 : 0,
    fill: it.color,
  }));

  const today0 = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const upcoming = (recurringQuery.data ?? [])
    .filter((r) => new Date(r.next_due) >= today0)
    .sort((a, b) => new Date(a.next_due).getTime() - new Date(b.next_due).getTime())
    .slice(0, 5);

  const goals = (goalsQuery.data ?? []).filter((g) => g.status !== "completed").slice(0, 4);

  return (
    <div className="space-y-lg animate-fade-in">
      <header className="flex flex-wrap items-end justify-between gap-md animate-slide-up">
        <div>
          <h1 className="text-h2 font-h2 text-text-primary">
            {greet}{userName ? `, ${userName}` : ""}
          </h1>
          <p className="mt-1 text-body text-text-muted">
            {isCurrentMonth ? (
              <>You're viewing the current month. Use the picker to look at any other.</>
            ) : (
              <>You're viewing <span className="font-medium text-text-primary">{monthHeading}</span>. Net worth and total balance always reflect today.</>
            )}
          </p>
        </div>
        <MonthPicker value={selectedMonth} onChange={setSelectedMonth} />
      </header>

      {/* KPI strip */}
      <div className="grid gap-md sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard
          label="Total balance"
          value={formatMoney(totalBalance, currency)}
          icon={Wallet}
          spark={balanceSpark}
          sparkValueFormatter={moneyFmt}
          hint="Liquid money you can spend right now: Cash + Savings accounts. Excludes investments and the Net cash flow running total."
        />
        <KpiCard
          label={`Income · ${monthHeading}`}
          value={formatMoney(selectedIncome, currency)}
          delta={
            incomeDelta != null
              ? {
                  value: `${incomeDelta >= 0 ? "+" : ""}${(incomeDelta * 100).toFixed(0)}% vs prev month`,
                  tone: incomeDelta >= 0 ? "up" : "down",
                }
              : undefined
          }
          icon={TrendingUp}
          spark={incomeSpark}
          sparkValueFormatter={moneyFmt}
          sparkTone="success"
          hint="Sum of every positive-amount transaction in this month, converted to your base currency at each transaction's historical rate."
        />
        <KpiCard
          label={`Expenses · ${monthHeading}`}
          value={formatMoney(selectedExpense, currency)}
          delta={
            expenseDelta != null
              ? {
                  value: `${expenseDelta >= 0 ? "+" : ""}${(expenseDelta * 100).toFixed(0)}% vs prev month`,
                  tone: expenseDelta <= 0 ? "up" : "down",
                }
              : undefined
          }
          icon={TrendingDown}
          spark={expenseSpark}
          sparkValueFormatter={moneyFmt}
          sparkTone="danger"
          hint="Sum of every negative-amount transaction in this month (always shown as a positive number), converted to your base currency."
        />
        <KpiCard
          label="Net worth"
          value={formatMoney(totals?.net_worth ?? 0, currency)}
          icon={TrendingUp}
          spark={netWorthSpark}
          sparkValueFormatter={moneyFmt}
          accent
          hint="Everything you own minus everything you owe: cash + savings + Paper Portfolio + manual assets − liabilities, all in your base currency."
        />
      </div>

      {/* Spending donut + Recent activity */}
      <div className="grid gap-md lg:grid-cols-5">
        <SectionCard
          title={`Spending · ${monthHeading}`}
          description={
            isCurrentMonth
              ? "How your spending breaks down this month"
              : `Historical view for ${monthHeading}`
          }
          action={
            <Link
              to="/reports"
              className="inline-flex items-center gap-1 text-body-small font-medium text-primary hover:underline focus-ring rounded"
            >
              View all <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          }
          className="lg:col-span-3"
        >
          {spendingQuery.isLoading ? (
            <Skeleton h="220px" />
          ) : donutData.length === 0 ? (
            <EmptySpending />
          ) : (
            <div className="flex flex-col items-center gap-lg md:flex-row md:gap-xl">
              <div className="relative h-[240px] w-full max-w-[260px] shrink-0">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie
                      data={donutData}
                      innerRadius={76}
                      outerRadius={108}
                      // No padding / corner radius — when one category
                      // dominates (e.g. Goals 98% + three categories at
                      // <1% each), `paddingAngle=3` × 4 slices = 12° of
                      // gap, which is wider than the entire sub-1%
                      // slice's arc. The tiny categories vanish into
                      // the padding and the donut looks broken (purple
                      // ring with a single floating green sliver). The
                      // `stroke` already separates adjacent slices
                      // visually.
                      paddingAngle={0}
                      cornerRadius={0}
                      dataKey="value"
                      stroke="rgb(var(--surface))"
                      strokeWidth={2}
                      isAnimationActive
                      animationDuration={500}
                    >
                      {donutData.map((s, i) => (
                        <Cell key={i} fill={s.fill} />
                      ))}
                    </Pie>
                    <Tooltip
                      contentStyle={{
                        borderRadius: 8,
                        border: "1px solid rgb(var(--border))",
                        fontSize: 13,
                        boxShadow: "0 10px 24px rgba(15, 23, 42, 0.06)",
                      }}
                      formatter={(v: number, name) => [formatMoney(v, currency), name]}
                    />
                  </PieChart>
                </ResponsiveContainer>
                <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
                  <span className="text-uppercase-label uppercase text-text-muted">Total</span>
                  <span className="text-h3 font-h3 tabular text-text-primary">
                    {formatMoney(totalExpense, currency)}
                  </span>
                  <span className="mt-0.5 text-uppercase-label uppercase text-text-muted">
                    {donutData.length} categor{donutData.length === 1 ? "y" : "ies"}
                  </span>
                </div>
              </div>
              <ul className="flex-1 space-y-1">
                {donutData.slice(0, 8).map((s) => (
                  <li
                    key={s.name}
                    className="group flex items-center justify-between gap-3 rounded-lg p-2 transition-colors hover:bg-surface-soft"
                  >
                    <div className="flex min-w-0 items-center gap-2">
                      <span
                        className="h-2.5 w-2.5 shrink-0 rounded-full"
                        style={{ backgroundColor: s.fill }}
                        aria-hidden="true"
                      />
                      <span className="truncate text-body-small font-medium text-text-primary">
                        {s.name}
                      </span>
                    </div>
                    <div className="flex items-baseline gap-2 text-body-small shrink-0">
                      <span className="text-text-muted tabular">{s.pct}%</span>
                      <span className="font-semibold tabular text-text-primary">
                        {formatMoney(s.value, currency)}
                      </span>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </SectionCard>

        <SectionCard
          title="Recent activity"
          action={
            <Link
              to="/transactions"
              className="inline-flex items-center gap-1 text-body-small font-medium text-primary hover:underline focus-ring rounded"
            >
              View all <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          }
          className="lg:col-span-2"
        >
          {recentTxQuery.isLoading ? (
            <Skeleton h="220px" />
          ) : (recentTxQuery.data?.transactions.length ?? 0) === 0 ? (
            <EmptyTransactions />
          ) : (
            <ul className="divide-y divide-border">
              {recentTxQuery.data!.transactions.map((t) => (
                <li
                  key={t.id}
                  className="flex items-center justify-between gap-3 py-2 transition-colors hover:bg-surface-soft -mx-3 px-3 rounded-lg"
                >
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-body-small font-medium text-text-primary">
                      {t.description}
                    </div>
                    <div className="text-uppercase-label uppercase text-text-muted">
                      {new Date(t.date).toLocaleDateString("en-US", { month: "short", day: "numeric" })}
                      {" · "}
                      {t.category_name ?? "Uncategorized"}
                    </div>
                  </div>
                  <span
                    className={cn(
                      "shrink-0 text-right tabular",
                      t.amount >= 0 ? "text-success" : "text-text-primary",
                    )}
                  >
                    <span className="block text-body-small font-semibold">
                      {t.amount >= 0 ? "+" : "−"}
                      {formatMoney(Math.abs(t.amount_base), currency)}
                    </span>
                    {t.currency !== currency && (
                      <span className="block text-uppercase-label normal-case text-text-muted">
                        ≈ {formatMoney(Math.abs(t.amount), t.currency)}
                      </span>
                    )}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </SectionCard>
      </div>

      {/* Upcoming planned payments */}
      <SectionCard
        title="Coming up"
        action={
          <Link
            to="/planned"
            className="inline-flex items-center gap-1 text-body-small font-medium text-primary hover:underline focus-ring rounded"
          >
            View all <ArrowRight className="h-3.5 w-3.5" />
          </Link>
        }
      >
          {upcoming.length === 0 ? (
            <p className="text-body-small text-text-muted">
              No payments scheduled. Add one on the Planned page.
            </p>
          ) : (
            <ul className="space-y-3">
              {upcoming.map((p) => (
                <li
                  key={p.id}
                  className="flex items-center justify-between gap-md transition-colors hover:bg-surface-soft -mx-3 px-3 py-2 rounded-lg"
                >
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-body-small font-medium text-text-primary">{p.name}</div>
                    <div className="text-uppercase-label uppercase text-text-muted">
                      {new Date(p.next_due).toLocaleDateString("en-US", { month: "short", day: "numeric" })}
                    </div>
                  </div>
                  <div className="shrink-0 text-right">
                    <div
                      className={cn(
                        "text-body-small font-semibold tabular",
                        p.is_income ? "text-success" : "text-danger",
                      )}
                    >
                      {p.is_income ? "+" : "−"}
                      {p.amount_base != null
                        ? formatMoney(p.amount_base, currency)
                        : formatMoney(p.amount, p.currency)}
                    </div>
                    {p.currency !== currency && p.amount_base != null && (
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
      </SectionCard>

      {/* Goals */}
      <SectionCard
        title="Your goals"
        action={
          <Link
            to="/goals"
            className="inline-flex items-center gap-1 text-body-small font-medium text-primary hover:underline focus-ring rounded"
          >
            View all <ArrowRight className="h-3.5 w-3.5" />
          </Link>
        }
      >
        {goals.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-3 py-md text-center">
            <p className="text-body-small text-text-muted">
              You don't have any active goals yet. Goals turn vague intentions into concrete monthly numbers.
            </p>
            <Button asChild variant="primary" size="sm">
              <Link to="/goals">
                <Plus className="h-3.5 w-3.5" /> Create your first goal
              </Link>
            </Button>
          </div>
        ) : (
          <div className="grid gap-md sm:grid-cols-2 lg:grid-cols-4">
            {goals.map((g) => (
              <div
                key={g.id}
                className="group rounded-xl border border-border bg-surface-soft/40 p-md transition-all hover:-translate-y-0.5 hover:border-primary/40 hover:bg-surface hover:shadow-card-hover"
              >
                <div className="text-body-small font-medium text-text-primary truncate">{g.name}</div>
                <div className="my-3 flex justify-center">
                  <ProgressRing pct={g.progress_pct} />
                </div>
                <GoalAmountDisplay
                  goal={g}
                  compact
                  className="text-center text-body-small"
                />
                <div className="mt-1 text-center text-uppercase-label uppercase text-text-muted">
                  {new Date(g.target_date).toLocaleDateString("en-US", { month: "short", year: "numeric" })}
                </div>
              </div>
            ))}
            {goals.length < 4 && (
              <Link
                to="/goals"
                className="flex items-center justify-center gap-2 rounded-xl border-2 border-dashed border-border bg-surface-soft/40 p-md text-body-small text-text-muted transition-all hover:border-primary hover:bg-primary-tint hover:text-primary focus-ring"
              >
                <Plus className="h-4 w-4" /> Add a goal
              </Link>
            )}
          </div>
        )}
      </SectionCard>

      {/* 6-month income vs expense */}
      <SectionCard
        title="Income vs expenses"
        description="Trailing 6 months — independent of the picker"
        contentClassName="h-[240px]"
      >
        {months.length === 0 ? (
          <Skeleton h="200px" />
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart
              data={months.map((m) => ({
                label: `${MONTH_NAMES[m.month - 1].slice(0, 3)} ${String(m.year).slice(-2)}`,
                income: m.income,
                expense: m.expense,
              }))}
              margin={{ top: 10, right: 16, left: 16, bottom: 12 }}
            >
              <defs>
                <linearGradient id="dash-income" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="rgb(16 185 129)" stopOpacity={0.28} />
                  <stop offset="100%" stopColor="rgb(16 185 129)" stopOpacity={0} />
                </linearGradient>
                <linearGradient id="dash-expense" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="rgb(239 68 68)" stopOpacity={0.24} />
                  <stop offset="100%" stopColor="rgb(239 68 68)" stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis
                dataKey="label"
                axisLine={false}
                tickLine={false}
                tickMargin={8}
                tick={{ fontSize: 11, fill: "rgb(var(--text-muted))" }}
              />
              <YAxis
                axisLine={false}
                tickLine={false}
                width={48}
                tickMargin={4}
                tickFormatter={(v) => `${(v / 1000).toFixed(0)}k`}
                tick={{ fontSize: 11, fill: "rgb(var(--text-muted))" }}
              />
              <Tooltip
                cursor={{ stroke: "rgb(var(--border))", strokeWidth: 1, strokeDasharray: "3 3" }}
                contentStyle={{
                  borderRadius: 8,
                  border: "1px solid rgb(var(--border))",
                  fontSize: 12,
                  boxShadow: "0 10px 24px rgba(15, 23, 42, 0.06)",
                }}
                formatter={(v: number, name) => [formatMoney(v, currency), name]}
              />
              <Legend
                verticalAlign="top"
                align="right"
                height={24}
                iconType="circle"
                iconSize={8}
                wrapperStyle={{ fontSize: 12, color: "rgb(var(--text-muted))" }}
              />
              <Area
                // `monotone` (not `natural`) so the smoothing never
                // overshoots peak data points — `natural` cubic-spline
                // overshoot was clipping the curve top at dataMax. See
                // KpiCard.tsx for the same fix.
                type="monotone"
                dataKey="income"
                name="Income"
                stroke="rgb(16 185 129)"
                strokeWidth={2.5}
                strokeLinecap="round"
                strokeLinejoin="round"
                fill="url(#dash-income)"
                dot={{ r: 3, fill: "rgb(16 185 129)", stroke: "white", strokeWidth: 1.5 }}
                activeDot={{ r: 5 }}
              />
              <Area
                type="monotone"
                dataKey="expense"
                name="Expenses"
                stroke="rgb(239 68 68)"
                strokeWidth={2.5}
                strokeLinecap="round"
                strokeLinejoin="round"
                fill="url(#dash-expense)"
                dot={{ r: 3, fill: "rgb(239 68 68)", stroke: "white", strokeWidth: 1.5 }}
                activeDot={{ r: 5 }}
              />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </SectionCard>
    </div>
  );
}

/* -------- helpers -------- */

function ProgressRing({ pct }: { pct: number }) {
  const r = 36;
  const c = 2 * Math.PI * r;
  const offset = c - (Math.min(100, pct) / 100) * c;
  return (
    <div className="relative h-20 w-20">
      <svg viewBox="0 0 100 100" className="h-full w-full -rotate-90">
        <circle cx="50" cy="50" r={r} fill="none" stroke="rgb(var(--surface-variant))" strokeWidth="9" />
        <circle
          cx="50"
          cy="50"
          r={r}
          fill="none"
          stroke="rgb(79 70 229)"
          strokeWidth="9"
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={offset}
          className="transition-all duration-700 ease-out"
        />
      </svg>
      <div className="absolute inset-0 flex items-center justify-center text-body font-semibold tabular">
        {Math.round(pct)}%
      </div>
    </div>
  );
}

function Skeleton({ h }: { h: string }) {
  return <div className="w-full animate-pulse rounded-lg bg-surface-soft" style={{ height: h }} />;
}

function EmptySpending() {
  return (
    <div className="flex h-[220px] flex-col items-center justify-center gap-2 text-center">
      <p className="text-body-small font-medium text-text-primary">No expenses this month</p>
      <p className="max-w-xs text-body-small text-text-muted">
        Add a transaction or import a CSV to see how your spending breaks down.
      </p>
      <Button asChild variant="primary" size="sm" className="mt-1">
        <Link to="/transactions">
          <Plus className="h-3.5 w-3.5" /> Go to Transactions
        </Link>
      </Button>
    </div>
  );
}

function EmptyTransactions() {
  return (
    <div className="flex h-[220px] flex-col items-center justify-center gap-2 text-center">
      <p className="text-body-small font-medium text-text-primary">No transactions yet</p>
      <p className="max-w-xs text-body-small text-text-muted">
        Add your first one or import from a bank CSV.
      </p>
      <Button asChild variant="primary" size="sm" className="mt-1">
        <Link to="/transactions">Go to Transactions</Link>
      </Button>
    </div>
  );
}
