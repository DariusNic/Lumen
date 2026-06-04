import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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
import { ArrowRight, Briefcase, DollarSign, Loader2, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { KpiCard } from "@/components/shared/KpiCard";
import { SectionCard } from "@/components/shared/SectionCard";
import { EmptyState } from "@/components/shared/EmptyState";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { qk } from "@/lib/queryKeys";
import { formatMoney, formatPercent } from "@/lib/format";
import { MoneyWithBase } from "@/components/shared/MoneyWithBase";
import { parseApiError } from "@/api/client";
import { cn } from "@/lib/utils";
import { useCurrency } from "@/hooks/useCurrency";
import { useFxRate } from "@/hooks/useFxRate";
import { FundsDialog } from "@/components/stocks/FundsDialog";
import * as portfolioApi from "@/api/portfolio.api";

const RANGES: portfolioApi.PortfolioRange[] = ["1M", "3M", "6M", "1Y", "ALL"];

// Stable, distinct slice colors for the allocation donut. Cycles when the
// user holds more than 8 unique tickers (very unlikely on a paper portfolio).
const SLICE_COLORS = [
  "rgb(79 70 229)", "rgb(16 185 129)", "rgb(6 182 212)", "rgb(245 158 11)",
  "rgb(236 72 153)", "rgb(139 92 246)", "rgb(34 197 94)", "rgb(249 115 22)",
];
const CASH_COLOR = "rgb(148 163 184)";

export default function PortfolioPage() {
  const qc = useQueryClient();
  const [range, setRange] = useState<portfolioApi.PortfolioRange>("3M");
  const [resetOpen, setResetOpen] = useState(false);
  const [fundsOpen, setFundsOpen] = useState(false);
  // FX rate for the USD → base subline on KPI cards. Stable across the
  // session (1h cache); `useFxRate` returns 1 when base is already USD so
  // the subline simply renders nothing in that case.
  const baseCurrency = useCurrency();
  const usdToBase = useFxRate("USD", baseCurrency);

  const portfolioQuery = useQuery({
    queryKey: qk.portfolio.current(),
    queryFn: portfolioApi.getPortfolio,
  });
  const tradesQuery = useQuery({
    queryKey: qk.portfolio.trades(),
    queryFn: () => portfolioApi.listTrades(50),
  });
  const historyQuery = useQuery({
    queryKey: qk.portfolio.history(range),
    queryFn: () => portfolioApi.getHistory(range),
  });

  const resetMutation = useMutation({
    mutationFn: portfolioApi.reset,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.portfolio.all() });
      qc.invalidateQueries({ queryKey: qk.accounts.all() });
      qc.invalidateQueries({ queryKey: qk.networth.all() });
      setResetOpen(false);
    },
  });

  if (portfolioQuery.isLoading) {
    return (
      <div className="flex items-center justify-center gap-2 py-2xl text-body-small text-text-muted">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading portfolio…
      </div>
    );
  }
  if (portfolioQuery.isError) {
    return (
      <SectionCard title="Portfolio">
        <p className="text-body-small text-danger">{parseApiError(portfolioQuery.error)}</p>
      </SectionCard>
    );
  }

  const portfolio = portfolioQuery.data!;
  const noActivity = portfolio.holdings.length === 0 && portfolio.trade_count === 0;

  if (noActivity) {
    return (
      <>
        <EmptyState
          icon={Briefcase}
          title="Your portfolio is ready, but empty"
          description={`You start with ${formatMoney(portfolio.initial_cash_usd, "USD")} of virtual cash. Browse stocks in the Markets tab and place your first paper trade.`}
          action={
            <Button variant="primary" asChild>
              <Link to="/markets">Go to Markets</Link>
            </Button>
          }
        />
      </>
    );
  }

  const allocationRaw = [
    ...portfolio.holdings
      .filter((h) => (h.market_value ?? 0) > 0)
      .map((h, i) => ({
        name: h.ticker,
        value: h.market_value ?? 0,
        fill: SLICE_COLORS[i % SLICE_COLORS.length],
      })),
    { name: "Cash", value: portfolio.cash_usd, fill: CASH_COLOR },
  ];
  // A tiny position (e.g. one $5 share of a $10k portfolio = 0.05%) would
  // render as a sub-pixel arc — visually missing. Inflate sub-0.5% slices
  // to a minimum visible angle, but keep the real `value` for the tooltip
  // so the number we report stays honest.
  const ALLOC_MIN_PCT = 0.5;
  const allocationTotal = allocationRaw.reduce((s, a) => s + a.value, 0);
  const allocation = allocationTotal > 0
    ? allocationRaw.map((a) => ({
        ...a,
        chartValue: Math.max(a.value, (ALLOC_MIN_PCT / 100) * allocationTotal),
      }))
    : allocationRaw.map((a) => ({ ...a, chartValue: a.value }));

  return (
    <div className="space-y-lg animate-fade-in">
      <header className="flex flex-wrap items-center justify-between gap-md">
        <div>
          <h1 className="text-h2 font-h2 text-text-primary">Portfolio</h1>
          <p className="text-body-small text-text-muted">
            Paper trading · started with {formatMoney(portfolio.initial_cash_usd, "USD")} of virtual cash ·{" "}
            <span className="tabular">{portfolio.trade_count}</span> trade{portfolio.trade_count === 1 ? "" : "s"}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setFundsOpen(true)}
          >
            <DollarSign className="h-4 w-4" /> Funds
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="text-text-muted"
            onClick={() => setResetOpen(true)}
          >
            <RotateCcw className="h-4 w-4" /> Reset portfolio
          </Button>
        </div>
      </header>

      {/* Base-as-primary convention: when the user's base differs from USD,
          the converted base-currency amount goes on the main line and the
          native USD value sits as the subline — matches Goals / Recurring /
          Transactions across the rest of the app. */}
      <div className="grid gap-md sm:grid-cols-3">
        <KpiCard
          label="Total value"
          value={
            baseCurrency !== "USD" && usdToBase != null
              ? formatMoney(portfolio.total_value_usd * usdToBase, baseCurrency, { maximumFractionDigits: 0 })
              : formatMoney(portfolio.total_value_usd, "USD")
          }
          valueSubline={
            baseCurrency !== "USD" && usdToBase != null
              ? formatMoney(portfolio.total_value_usd, "USD")
              : undefined
          }
          accent
        />
        <KpiCard
          label="Total return"
          value={
            baseCurrency !== "USD" && usdToBase != null
              ? `${portfolio.total_return_usd >= 0 ? "+" : ""}${formatMoney(portfolio.total_return_usd * usdToBase, baseCurrency, { maximumFractionDigits: 0 })}`
              : `${portfolio.total_return_usd >= 0 ? "+" : ""}${formatMoney(portfolio.total_return_usd, "USD")}`
          }
          valueSubline={
            baseCurrency !== "USD" && usdToBase != null
              ? `${portfolio.total_return_usd >= 0 ? "+" : ""}${formatMoney(portfolio.total_return_usd, "USD")}`
              : undefined
          }
          delta={{
            value: formatPercent(portfolio.total_return_pct / 100, { signed: true, digits: 2 }),
            tone: portfolio.total_return_usd >= 0 ? "up" : "down",
          }}
        />
        <KpiCard
          label="Cash balance"
          value={
            baseCurrency !== "USD" && usdToBase != null
              ? formatMoney(portfolio.cash_usd * usdToBase, baseCurrency, { maximumFractionDigits: 0 })
              : formatMoney(portfolio.cash_usd, "USD")
          }
          valueSubline={
            baseCurrency !== "USD" && usdToBase != null
              ? formatMoney(portfolio.cash_usd, "USD")
              : undefined
          }
        />
      </div>

      <div className="grid gap-md lg:grid-cols-5">
        <SectionCard title="Allocation" className="lg:col-span-2" contentClassName="h-[280px]">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={allocation}
                // `chartValue` is the inflated-for-display field so tiny
                // positions still render a visible slice. Tooltip pulls the
                // truth from `value` via item.payload so it remains exact.
                // `paddingAngle=0` mirrors the Dashboard/Reports donut fix.
                dataKey="chartValue"
                innerRadius={50}
                outerRadius={85}
                stroke="none"
                paddingAngle={0}
              >
                {allocation.map((a, i) => (
                  <Cell key={i} fill={a.fill} />
                ))}
              </Pie>
              <Tooltip
                formatter={(_v: number, _name, item) =>
                  formatMoney(item?.payload?.value ?? 0, "USD")
                }
              />
              <Legend
                verticalAlign="bottom"
                height={36}
                iconType="circle"
                wrapperStyle={{ fontSize: 12 }}
              />
            </PieChart>
          </ResponsiveContainer>
        </SectionCard>

        <SectionCard
          title="Equity curve"
          description="Total portfolio value over time, based on your trades and daily closing prices."
          className="lg:col-span-3"
          action={
            <div className="flex gap-1">
              {RANGES.map((r) => (
                <button
                  key={r}
                  onClick={() => setRange(r)}
                  className={cn(
                    "rounded-md px-2 py-1 text-uppercase-label uppercase transition-colors focus-ring",
                    range === r
                      ? "bg-primary-tint text-primary"
                      : "text-text-muted hover:bg-surface-soft hover:text-text-primary",
                  )}
                >
                  {r}
                </button>
              ))}
            </div>
          }
          contentClassName="h-[280px]"
        >
          {historyQuery.isLoading ? (
            <div className="flex h-full items-center justify-center text-body-small text-text-muted">
              <Loader2 className="h-4 w-4 animate-spin" />
            </div>
          ) : historyQuery.isError || (historyQuery.data?.points.length ?? 0) === 0 ? (
            <p className="py-md text-body-small text-text-muted">
              No history yet — make your first trade to populate the curve.
            </p>
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={historyQuery.data!.points}>
                <defs>
                  <linearGradient id="eq" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="rgb(79 70 229)" stopOpacity={0.32} />
                    <stop offset="100%" stopColor="rgb(79 70 229)" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <XAxis
                  dataKey="date"
                  tickFormatter={(d) => new Date(d).toLocaleDateString("en-US", { month: "short", day: "numeric" })}
                  axisLine={false}
                  tickLine={false}
                  tick={{ fontSize: 10, fill: "rgb(var(--text-muted))" }}
                  minTickGap={32}
                />
                <YAxis
                  tickFormatter={(v) => `$${(v / 1000).toFixed(1)}k`}
                  axisLine={false}
                  tickLine={false}
                  tick={{ fontSize: 10, fill: "rgb(var(--text-muted))" }}
                  width={56}
                  domain={["dataMin - 200", "dataMax + 200"]}
                />
                <Tooltip
                  contentStyle={{
                    borderRadius: 8,
                    border: "1px solid rgb(var(--border))",
                    fontSize: 12,
                  }}
                  formatter={(v: number) => [formatMoney(v, "USD"), "Total"]}
                  labelFormatter={(d) => new Date(d).toLocaleDateString("en-US")}
                />
                <Area
                  type="monotone"
                  dataKey="total_value_usd"
                  stroke="rgb(79 70 229)"
                  strokeWidth={2.5}
                  fill="url(#eq)"
                />
              </AreaChart>
            </ResponsiveContainer>
          )}
        </SectionCard>
      </div>

      {/* Holdings */}
      {portfolio.holdings.length > 0 && (
        <SectionCard title="Holdings" noPadding>
          <div className="overflow-x-auto">
            <table className="w-full text-body-small">
              <thead>
                <tr className="border-b border-border text-uppercase-label uppercase text-text-muted">
                  <th className="px-md py-3 text-left font-medium">Ticker</th>
                  <th className="px-md py-3 text-right font-medium">Qty</th>
                  <th className="px-md py-3 text-right font-medium">Avg buy price</th>
                  <th className="px-md py-3 text-right font-medium">Last price</th>
                  <th className="px-md py-3 text-right font-medium">Value</th>
                  <th className="px-md py-3 text-right font-medium">Unrealized P&amp;L</th>
                  <th className="px-md py-3 text-right font-medium">Allocation</th>
                  <th className="w-16 px-md py-3"></th>
                </tr>
              </thead>
              <tbody>
                {portfolio.holdings.map((h) => {
                  const value = h.market_value ?? h.qty * h.avg_cost;
                  const pnl = h.unrealized_pnl ?? 0;
                  const pnlPct = h.unrealized_pnl_pct ?? 0;
                  const alloc = portfolio.total_value_usd > 0
                    ? (value / portfolio.total_value_usd) * 100
                    : 0;
                  return (
                    <tr key={h.ticker} className="border-b border-border/60 transition-colors hover:bg-surface-soft last:border-0">
                      <td className="px-md py-3">
                        <div className="font-mono font-bold tabular text-text-primary">{h.ticker}</div>
                      </td>
                      <td className="px-md py-3 text-right tabular font-mono">{h.qty}</td>
                      <td className="px-md py-3 text-right tabular">
                        <MoneyWithBase amount={h.avg_cost} currency="USD" variant="block" />
                      </td>
                      <td className="px-md py-3 text-right tabular">
                        {h.last_price != null ? (
                          <MoneyWithBase amount={h.last_price} currency="USD" variant="block" />
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="px-md py-3 text-right tabular font-semibold">
                        <MoneyWithBase amount={value} currency="USD" variant="block" />
                      </td>
                      <td className={cn(
                        "px-md py-3 text-right tabular font-semibold",
                        pnl >= 0 ? "text-success" : "text-danger",
                      )}>
                        {baseCurrency !== "USD" && usdToBase != null ? (
                          // Base primary + percent on the same line, native USD
                          // on the subline. Mirrors the existing dollar-only
                          // layout the user is used to ("$X.XX (+Y.Y%)") just
                          // with the base currency replacing the dollar.
                          <span className="inline-flex flex-col items-end leading-tight">
                            <span>
                              {pnl >= 0 ? "+" : ""}
                              {formatMoney(pnl * usdToBase, baseCurrency)}
                              {" "}({formatPercent(pnlPct / 100, { signed: true, digits: 1 })})
                            </span>
                            <span className="text-uppercase-label text-text-muted">
                              {pnl >= 0 ? "+" : ""}{formatMoney(pnl, "USD")}
                            </span>
                          </span>
                        ) : (
                          <>
                            {pnl >= 0 ? "+" : ""}{formatMoney(pnl, "USD")}
                            {" "}({formatPercent(pnlPct / 100, { signed: true, digits: 1 })})
                          </>
                        )}
                      </td>
                      <td className="px-md py-3 text-right tabular text-text-muted">
                        {formatPercent(alloc / 100, { digits: 1 })}
                      </td>
                      <td className="px-md py-3">
                        <Button variant="ghost" size="sm" asChild>
                          <Link to={`/stocks/${h.ticker}`}>
                            Trade <ArrowRight className="h-3.5 w-3.5" />
                          </Link>
                        </Button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </SectionCard>
      )}

      {/* Trade history */}
      <SectionCard title="Trade history" noPadding>
        <div className="overflow-x-auto">
          <table className="w-full text-body-small">
            <thead>
              <tr className="border-b border-border text-uppercase-label uppercase text-text-muted">
                <th className="px-md py-3 text-left font-medium">Date</th>
                <th className="px-md py-3 text-left font-medium">Ticker</th>
                <th className="px-md py-3 text-left font-medium">Side</th>
                <th className="px-md py-3 text-right font-medium">Qty</th>
                <th className="px-md py-3 text-right font-medium">Price</th>
                <th className="px-md py-3 text-right font-medium">Total</th>
                <th className="px-md py-3 text-right font-medium">Realized P&amp;L</th>
              </tr>
            </thead>
            <tbody>
              {(tradesQuery.data ?? []).map((t) => {
                // Deposit/withdrawal rows reuse the trades table with
                // ticker="CASH", qty=1, price=total=amount. Render them with
                // dashes in qty/price and a friendlier ticker label so they
                // don't read like trades. Color: deposit = green (cash in),
                // withdrawal = red (cash out), matching the buy/sell scheme.
                const isFunds = t.side === "deposit" || t.side === "withdrawal";
                const sideTone =
                  t.side === "buy" || t.side === "deposit"
                    ? "bg-success/10 text-success"
                    : "bg-danger/10 text-danger";
                return (
                  <tr key={t.id} className="border-b border-border/60 last:border-0">
                    <td className="px-md py-3 text-text-muted whitespace-nowrap">
                      {new Date(t.date).toLocaleString("en-US", {
                        month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
                      })}
                    </td>
                    <td className="px-md py-3 font-mono font-semibold">
                      {isFunds ? "Cash" : t.ticker}
                    </td>
                    <td className="px-md py-3">
                      <span className={cn(
                        "rounded-full px-2 py-0.5 text-uppercase-label uppercase",
                        sideTone,
                      )}>
                        {t.side}
                      </span>
                    </td>
                    <td className="px-md py-3 text-right tabular font-mono">
                      {isFunds ? "—" : t.qty}
                    </td>
                    <td className="px-md py-3 text-right tabular">
                      {isFunds ? (
                        "—"
                      ) : (
                        <MoneyWithBase amount={t.price} currency="USD" variant="block" />
                      )}
                    </td>
                    <td className="px-md py-3 text-right tabular font-semibold">
                      <MoneyWithBase amount={t.total} currency="USD" variant="block" />
                    </td>
                    <td className={cn(
                      "px-md py-3 text-right tabular",
                      t.realized_pnl == null
                        ? "text-text-muted"
                        : t.realized_pnl >= 0 ? "text-success" : "text-danger",
                    )}>
                      {t.realized_pnl == null
                        ? "—"
                        : `${t.realized_pnl >= 0 ? "+" : ""}${formatMoney(t.realized_pnl, "USD")}`}
                    </td>
                  </tr>
                );
              })}
              {(tradesQuery.data ?? []).length === 0 && (
                <tr>
                  <td colSpan={7} className="px-md py-md text-center text-body-small text-text-muted">
                    No trades yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </SectionCard>

      {/* Reset confirm */}
      <ResetConfirmDialog
        open={resetOpen}
        onOpenChange={setResetOpen}
        onConfirm={() => resetMutation.mutate()}
        isPending={resetMutation.isPending}
        error={resetMutation.isError ? parseApiError(resetMutation.error) : null}
        portfolio={portfolio}
      />

      <FundsDialog
        open={fundsOpen}
        onOpenChange={setFundsOpen}
        currentCashUsd={portfolio.cash_usd}
      />
    </div>
  );
}


function ResetConfirmDialog({
  open,
  onOpenChange,
  onConfirm,
  isPending,
  error,
  portfolio,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  onConfirm: () => void;
  isPending: boolean;
  error: string | null;
  portfolio: portfolioApi.Portfolio;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Reset paper portfolio?</DialogTitle>
          <DialogDescription>
            Clears all holdings, removes your trade history, and restores cash to{" "}
            {formatMoney(portfolio.initial_cash_usd, "USD")}. This can't be undone.
          </DialogDescription>
        </DialogHeader>
        <div className="rounded-lg border border-border bg-surface-soft p-3 text-body-small space-y-1">
          <Row label="Current value" value={formatMoney(portfolio.total_value_usd, "USD")} />
          <Row
            label="Total return"
            value={`${portfolio.total_return_usd >= 0 ? "+" : ""}${formatMoney(portfolio.total_return_usd, "USD")} (${formatPercent(portfolio.total_return_pct / 100, { signed: true, digits: 2 })})`}
            tone={portfolio.total_return_usd >= 0 ? "success" : "danger"}
          />
          <Row label="Trades" value={String(portfolio.trade_count)} />
        </div>
        {error && (
          <div role="alert" className="rounded-lg border border-danger/30 bg-danger/10 p-3 text-body-small text-danger">
            {error}
          </div>
        )}
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={isPending}>
            Cancel
          </Button>
          <Button variant="danger" onClick={onConfirm} disabled={isPending}>
            {isPending ? (
              <><Loader2 className="h-4 w-4 animate-spin" /> Resetting…</>
            ) : (
              <><RotateCcw className="h-4 w-4" /> Reset portfolio</>
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}


function Row({ label, value, tone = "default" }: { label: string; value: string; tone?: "default" | "success" | "danger" }) {
  return (
    <div className="flex justify-between">
      <span className="text-text-muted">{label}</span>
      <span className={cn(
        "tabular",
        tone === "success" && "text-success font-semibold",
        tone === "danger" && "text-danger font-semibold",
      )}>
        {value}
      </span>
    </div>
  );
}
