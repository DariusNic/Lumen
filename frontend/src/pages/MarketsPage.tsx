import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Loader2, Search, TrendingDown, TrendingUp } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { SectionCard } from "@/components/shared/SectionCard";
import { SignalPill, type Signal } from "@/components/shared/SignalBadge";
import { qk } from "@/lib/queryKeys";
import { formatPercent } from "@/lib/format";
import { MoneyWithBase } from "@/components/shared/MoneyWithBase";
import { parseApiError } from "@/api/client";
import { cn } from "@/lib/utils";
import * as stocksApi from "@/api/stocks.api";

type SignalFilter = "all" | Signal;
type SortMode = "default" | "strongest" | "weakest";

export default function MarketsPage() {
  const [query, setQuery] = useState("");
  const [sector, setSector] = useState<string>("all");
  const [signalFilter, setSignalFilter] = useState<SignalFilter>("all");
  const [sortMode, setSortMode] = useState<SortMode>("default");

  const stocksQuery = useQuery({
    queryKey: qk.stocks.list(),
    queryFn: stocksApi.listStocks,
  });
  // Cache signals for 30 minutes — the daily refresh job overwrites bars
  // at 21:00 UTC so a 30-minute stale window is plenty fresh.
  const signalsQuery = useQuery({
    queryKey: qk.stocks.signalsBatch(),
    queryFn: stocksApi.getAllSignals,
    staleTime: 30 * 60_000,
  });

  // Build a fast lookup of signal-by-ticker for the table.
  const signalByTicker = useMemo(() => {
    const map = new Map<string, stocksApi.SignalResponse>();
    for (const s of signalsQuery.data?.signals ?? []) map.set(s.ticker, s);
    return map;
  }, [signalsQuery.data]);

  // Sectors are derived from the universe so the dropdown stays in sync
  // even when we add tickers.
  const sectors = useMemo(() => {
    const set = new Set<string>();
    for (const t of stocksQuery.data?.tickers ?? []) set.add(t.sector);
    return ["all", ...[...set].sort()];
  }, [stocksQuery.data]);

  const rows = useMemo(() => {
    const tickers = stocksQuery.data?.tickers ?? [];
    const filtered = tickers
      .map((t) => ({
        ...t,
        signal: signalByTicker.get(t.ticker) ?? null,
      }))
      .filter((row) => {
        if (sector !== "all" && row.sector !== sector) return false;
        if (signalFilter !== "all" && row.signal?.label !== signalFilter) return false;
        if (query) {
          const q = query.toLowerCase();
          if (
            !row.ticker.toLowerCase().includes(q) &&
            !row.name.toLowerCase().includes(q)
          ) return false;
        }
        return true;
      });
    if (sortMode === "default") return filtered;
    // Sort by signal confidence. Rows without a signal (model artifact
    // missing, insufficient history, etc.) always trail to the bottom so
    // they don't pollute the "strongest / weakest" head of the list.
    // Ticker alphabetic tiebreaker keeps the order stable across renders.
    return [...filtered].sort((a, b) => {
      const ca = a.signal?.confidence ?? -1;
      const cb = b.signal?.confidence ?? -1;
      if (ca === -1 && cb === -1) return a.ticker.localeCompare(b.ticker);
      if (ca === -1) return 1;
      if (cb === -1) return -1;
      if (ca !== cb) return sortMode === "strongest" ? cb - ca : ca - cb;
      return a.ticker.localeCompare(b.ticker);
    });
  }, [stocksQuery.data, signalByTicker, sector, signalFilter, query, sortMode]);

  const counts = useMemo(() => {
    const c = { BUY: 0, HOLD: 0, SELL: 0 };
    for (const row of rows) {
      const lab = row.signal?.label;
      if (lab === "BUY" || lab === "HOLD" || lab === "SELL") c[lab] += 1;
    }
    return c;
  }, [rows]);

  if (stocksQuery.isLoading) {
    return (
      <div className="flex items-center justify-center gap-2 py-2xl text-body-small text-text-muted">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading markets…
      </div>
    );
  }
  if (stocksQuery.isError) {
    return (
      <SectionCard title="Markets">
        <p className="text-body-small text-danger">{parseApiError(stocksQuery.error)}</p>
        <p className="mt-2 text-body-small text-text-muted">
          We couldn't load the market list right now. Please refresh the page in a moment.
        </p>
      </SectionCard>
    );
  }
  if ((stocksQuery.data?.tickers.length ?? 0) === 0) {
    return (
      <SectionCard title="Markets" description="The market list is currently empty">
        <p className="text-body-small text-text-muted">
          No tickers are available yet. Check back shortly.
        </p>
      </SectionCard>
    );
  }

  return (
    <div className="space-y-lg animate-fade-in">
      <header className="flex flex-wrap items-center justify-between gap-md">
        <div>
          <h1 className="text-h2 font-h2 text-text-primary">Markets</h1>
          <p className="text-body-small text-text-muted">
            US stocks · AI Buy / Hold / Sell signals from technical indicators ·{" "}
            <span className="tabular">{stocksQuery.data?.total ?? 0}</span> tracked
          </p>
        </div>
        {signalsQuery.isLoading && (
          <div className="inline-flex items-center gap-2 text-body-small text-text-muted">
            <Loader2 className="h-3.5 w-3.5 animate-spin" /> Computing signals…
          </div>
        )}
        {signalsQuery.isError && (
          <div className="rounded-lg border border-warning/30 bg-warning/10 px-3 py-1 text-body-small text-warning-700">
            AI signals are temporarily unavailable
          </div>
        )}
      </header>

      {/* Filters */}
      <SectionCard noPadding contentClassName="p-md">
        <div className="grid gap-3 lg:grid-cols-[1fr_180px_180px_220px]">
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-muted" />
            <Input
              type="search"
              placeholder="Search ticker or name"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="pl-10"
            />
          </div>
          <select
            value={sector}
            onChange={(e) => setSector(e.target.value)}
            className="flex h-10 rounded-lg border border-border bg-surface px-3 text-body focus-ring"
          >
            {sectors.map((s) => (
              <option key={s} value={s}>
                {s === "all" ? "All sectors" : s}
              </option>
            ))}
          </select>
          <select
            value={signalFilter}
            onChange={(e) => setSignalFilter(e.target.value as SignalFilter)}
            className="flex h-10 rounded-lg border border-border bg-surface px-3 text-body focus-ring"
          >
            <option value="all">All signals</option>
            <option value="BUY">BUY only</option>
            <option value="HOLD">HOLD only</option>
            <option value="SELL">SELL only</option>
          </select>
          {/* Sort by signal strength (= confidence). Rows without a signal
              always trail; ties broken alphabetically. Combines naturally
              with the signal filter: "BUY only" + "Strongest first" = top
              buy opportunities. */}
          <select
            value={sortMode}
            onChange={(e) => setSortMode(e.target.value as SortMode)}
            className="flex h-10 rounded-lg border border-border bg-surface px-3 text-body focus-ring"
            aria-label="Sort"
          >
            <option value="default">Default order</option>
            <option value="strongest">Strongest signal first</option>
            <option value="weakest">Weakest signal first</option>
          </select>
        </div>
      </SectionCard>

      <div className="flex flex-wrap gap-3 text-body-small">
        <span className="inline-flex items-center gap-1.5 rounded-full bg-success/10 px-3 py-1 text-success">
          <TrendingUp className="h-3.5 w-3.5" /> {counts.BUY} buys
        </span>
        <span className="inline-flex items-center gap-1.5 rounded-full bg-surface-variant px-3 py-1 text-text-muted">
          {counts.HOLD} holds
        </span>
        <span className="inline-flex items-center gap-1.5 rounded-full bg-danger/10 px-3 py-1 text-danger">
          <TrendingDown className="h-3.5 w-3.5" /> {counts.SELL} sells
        </span>
        <span className="ml-auto text-text-muted">
          Showing {rows.length} of {stocksQuery.data?.total ?? 0}
        </span>
      </div>

      <SectionCard noPadding>
        <div className="overflow-x-auto">
          <table className="w-full text-body-small">
            <thead>
              <tr className="border-b border-border text-uppercase-label uppercase text-text-muted">
                <th className="px-md py-3 text-left font-medium">Ticker</th>
                <th className="px-md py-3 text-left font-medium">Sector</th>
                <th className="px-md py-3 text-right font-medium">Last close</th>
                <th className="px-md py-3 text-right font-medium">1d</th>
                <th className="px-md py-3 text-right font-medium">5d</th>
                <th className="px-md py-3 text-left font-medium">Signal</th>
                <th className="w-20 px-md py-3"></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr
                  key={row.ticker}
                  className="group border-b border-border/60 transition-colors hover:bg-surface-soft last:border-0"
                >
                  <td className="px-md py-3">
                    <div className="font-mono font-bold tracking-tight text-text-primary">
                      {row.ticker}
                    </div>
                    <div className="text-uppercase-label uppercase text-text-muted truncate max-w-[200px]">
                      {row.name}
                    </div>
                  </td>
                  <td className="px-md py-3 text-text-muted">{row.sector}</td>
                  <td className="px-md py-3 text-right">
                    <div className="font-semibold tabular text-text-primary">
                      <MoneyWithBase amount={row.last_close} currency="USD" variant="block" />
                    </div>
                  </td>
                  <td className="px-md py-3 text-right">
                    <PctCell value={row.change_1d_pct} />
                  </td>
                  <td className="px-md py-3 text-right">
                    <PctCell value={row.change_5d_pct} />
                  </td>
                  <td className="px-md py-3">
                    {row.signal ? (
                      <SignalPill
                        signal={row.signal.label}
                        confidence={row.signal.confidence}
                      />
                    ) : signalsQuery.isLoading ? (
                      <span className="inline-block h-6 w-16 animate-pulse rounded-full bg-surface-variant" />
                    ) : (
                      <span className="text-uppercase-label uppercase text-text-muted">—</span>
                    )}
                  </td>
                  <td className="px-md py-3">
                    <Button variant="ghost" size="sm" asChild>
                      <Link to={`/stocks/${row.ticker}`}>View</Link>
                    </Button>
                  </td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-md py-2xl text-center text-body-small text-text-muted">
                    No stocks match the current filters.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </SectionCard>
    </div>
  );
}

function PctCell({ value }: { value: number | null }) {
  if (value === null) return <span className="text-text-muted">—</span>;
  return (
    <span
      className={cn(
        "tabular font-semibold",
        value > 0 ? "text-success" : value < 0 ? "text-danger" : "text-text-muted",
      )}
    >
      {formatPercent(value, { signed: true, digits: 2 })}
    </span>
  );
}
