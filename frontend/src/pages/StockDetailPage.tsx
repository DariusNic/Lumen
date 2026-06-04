import { useState, type ReactNode } from "react";
import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Loader2, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { SectionCard } from "@/components/shared/SectionCard";
import { SignalBadge } from "@/components/shared/SignalBadge";
import { CandlestickChart } from "@/components/stocks/CandlestickChart";
import { ExplanationWithTerms } from "@/components/stocks/ExplanationWithTerms";
import { TradeDialog } from "@/components/stocks/TradeDialog";
import { qk } from "@/lib/queryKeys";
import { formatPercent } from "@/lib/format";
import { MoneyWithBase } from "@/components/shared/MoneyWithBase";
import { parseApiError } from "@/api/client";
import { cn } from "@/lib/utils";
import * as stocksApi from "@/api/stocks.api";

const RANGES: stocksApi.StockRange[] = ["1M", "3M", "6M", "1Y", "ALL"];

export default function StockDetailPage() {
  const { ticker = "AAPL" } = useParams();
  const T = ticker.toUpperCase();
  const [range, setRange] = useState<stocksApi.StockRange>("3M");
  const [tradeOpen, setTradeOpen] = useState(false);
  const [tradeSide, setTradeSide] = useState<"buy" | "sell">("buy");

  const detailQuery = useQuery({
    queryKey: qk.stocks.detail(T, range),
    queryFn: () => stocksApi.getTicker(T, range),
  });
  const signalQuery = useQuery({
    queryKey: qk.stocks.signal(T),
    queryFn: () => stocksApi.getSignal(T),
    staleTime: 30 * 60_000,
  });

  if (detailQuery.isLoading) {
    return (
      <div className="flex items-center justify-center gap-2 py-2xl text-body-small text-text-muted">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading {T}…
      </div>
    );
  }
  if (detailQuery.isError) {
    return (
      <SectionCard title={T}>
        <p className="text-body-small text-danger">{parseApiError(detailQuery.error)}</p>
      </SectionCard>
    );
  }

  const detail = detailQuery.data!;
  const bars = detail.history;
  const last = bars[bars.length - 1] ?? null;
  const prev = bars[bars.length - 2] ?? null;
  const lastClose = last?.close ?? null;
  const change = last && prev ? last.close - prev.close : null;
  const changePct = change !== null && prev ? (change / prev.close) * 100 : null;

  const signal = signalQuery.data;

  return (
    <div className="space-y-lg animate-fade-in">
      {/* Header */}
      <header className="flex flex-wrap items-start justify-between gap-md">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="font-mono text-h1 font-bold tracking-tight text-text-primary">
              {T}
            </h1>
            <span className="rounded-full bg-surface-variant px-2 py-0.5 text-uppercase-label uppercase text-text-muted">
              {detail.sector}
            </span>
          </div>
          <p className="text-body-large text-text-muted">{detail.name}</p>
          {lastClose != null && (
            <p className="mt-2 text-h3 font-h3 tabular text-text-primary">
              <MoneyWithBase amount={lastClose} currency="USD" />{" "}
              {change != null && changePct != null && (
                <span className={cn(
                  "ml-2 text-body-small font-semibold",
                  change >= 0 ? "text-success" : "text-danger",
                )}>
                  {change >= 0 ? "+" : ""}
                  {change.toFixed(2)} ({formatPercent(changePct / 100, { signed: true, digits: 2 })})
                </span>
              )}
            </p>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="success"
            onClick={() => { setTradeSide("buy"); setTradeOpen(true); }}
          >
            Buy
          </Button>
          <Button
            variant="danger"
            onClick={() => { setTradeSide("sell"); setTradeOpen(true); }}
          >
            Sell
          </Button>
        </div>
      </header>

      {/* Range selector + price chart */}
      <SectionCard
        title="Price"
        description="Daily prices, adjusted for splits and dividends."
        action={
          <div className="flex gap-1">
            {RANGES.map((r) => (
              <button
                key={r}
                onClick={() => setRange(r)}
                className={cn(
                  "rounded-md px-3 py-1 text-uppercase-label uppercase transition-colors focus-ring",
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
      >
        {bars.length === 0 ? (
          <p className="py-md text-body-small text-text-muted">
            No price history available for {T} right now.
          </p>
        ) : (
          <CandlestickChart bars={bars} height={420} />
        )}
      </SectionCard>

      {/* Signal panel + key stats side by side */}
      <div className="grid gap-md lg:grid-cols-5">
        <SectionCard
          title="AI Signal"
          description="Buy / Hold / Sell call based on technical indicators, looking 5 trading days ahead."
          className="lg:col-span-2"
        >
          {signalQuery.isLoading ? (
            <div className="flex items-center gap-2 py-md text-body-small text-text-muted">
              <Loader2 className="h-4 w-4 animate-spin" /> Computing…
            </div>
          ) : signalQuery.isError ? (
            <div role="alert" className="rounded-lg border border-warning/30 bg-warning/10 p-3 text-body-small text-warning-700">
              AI signal is temporarily unavailable for {T}.
            </div>
          ) : signal ? (
            <div className="space-y-md">
              <div className="flex items-center gap-md">
                <SignalBadge signal={signal.label} confidence={signal.confidence} />
                <div className="flex-1 space-y-1">
                  {(["BUY", "HOLD", "SELL"] as const).map((lab) => (
                    <ProbBar
                      key={lab}
                      label={lab}
                      value={signal.probabilities[lab] ?? 0}
                      active={lab === signal.label}
                    />
                  ))}
                </div>
              </div>
              <div className="rounded-lg border border-border bg-surface-soft p-3 text-body-small">
                <div className="mb-1 inline-flex items-center gap-1.5 text-uppercase-label uppercase text-primary">
                  <Sparkles className="h-3.5 w-3.5" /> Why
                </div>
                <ExplanationWithTerms text={signal.explanation} />
              </div>
            </div>
          ) : (
            <p className="text-body-small text-text-muted">No signal available.</p>
          )}
        </SectionCard>

        <SectionCard title="Key stats" className="lg:col-span-3">
          <KeyStats bars={bars} range={range} />
        </SectionCard>
      </div>

      <TradeDialog
        open={tradeOpen}
        onOpenChange={setTradeOpen}
        ticker={T}
        lastClose={lastClose}
        initialSide={tradeSide}
      />
    </div>
  );
}


function ProbBar({ label, value, active }: { label: string; value: number; active: boolean }) {
  const pct = value * 100;
  const tone = label === "BUY" ? "bg-success" : label === "SELL" ? "bg-danger" : "bg-text-muted";
  return (
    <div className="space-y-0.5">
      <div className="flex justify-between text-uppercase-label uppercase text-text-muted">
        <span className={cn(active && "text-text-primary font-semibold")}>{label}</span>
        <span className={cn("tabular", active && "text-text-primary font-semibold")}>
          {formatPercent(value, { digits: 0 })}
        </span>
      </div>
      <div className="h-1.5 w-full rounded-full bg-surface-variant">
        <div className={cn("h-full rounded-full", tone)} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}


function KeyStats({ bars, range }: { bars: stocksApi.OHLCVBar[]; range: stocksApi.StockRange }) {
  if (bars.length === 0) return null;
  const last = bars[bars.length - 1];
  const high = Math.max(...bars.map((b) => b.high));
  const low = Math.min(...bars.map((b) => b.low));
  const avgVol = bars.reduce((s, b) => s + b.volume, 0) / bars.length;
  const rangeLabel = range === "ALL" ? "All-time" : range;

  // Mix of money + non-money fields. The money cells render with
  // `MoneyWithBase` so they show the base-currency equivalent inline.
  const stats: { label: string; node: ReactNode }[] = [
    { label: "Day high", node: <MoneyWithBase amount={last.high} currency="USD" /> },
    { label: "Day low", node: <MoneyWithBase amount={last.low} currency="USD" /> },
    { label: "Day volume", node: formatVolume(last.volume) },
    { label: `${rangeLabel} high`, node: <MoneyWithBase amount={high} currency="USD" /> },
    { label: `${rangeLabel} low`, node: <MoneyWithBase amount={low} currency="USD" /> },
    { label: `${rangeLabel} avg volume`, node: formatVolume(avgVol) },
  ];

  return (
    <dl className="grid grid-cols-2 gap-x-md gap-y-sm sm:grid-cols-3">
      {stats.map(({ label, node }) => (
        <div key={label}>
          <dt className="text-uppercase-label uppercase text-text-muted">{label}</dt>
          <dd className="font-semibold tabular text-text-primary">{node}</dd>
        </div>
      ))}
    </dl>
  );
}


function formatVolume(v: number): string {
  if (v >= 1e9) return `${(v / 1e9).toFixed(2)}B`;
  if (v >= 1e6) return `${(v / 1e6).toFixed(2)}M`;
  if (v >= 1e3) return `${(v / 1e3).toFixed(2)}K`;
  return v.toFixed(0);
}
