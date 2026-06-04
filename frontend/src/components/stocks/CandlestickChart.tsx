import { useEffect, useMemo, useRef } from "react";
import {
  Area,
  AreaChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  CandlestickSeries,
  ColorType,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type Time,
} from "lightweight-charts";
import type { OHLCVBar } from "@/api/stocks.api";
import { formatMoney } from "@/lib/format";

interface Props {
  bars: OHLCVBar[];
  height?: number;
}

/**
 * Two-mode price chart:
 *   - md+ (≥ 768 px): full lightweight-charts candlestick.
 *   - < md          : Recharts AreaChart on close prices only — degraded
 *                     gracefully so phones still render *something*.
 *
 * Using `useMediaQuery` would be cleaner than the `md:hidden` / `hidden md:block`
 * dance, but this avoids pulling in another hook for one component.
 */
export function CandlestickChart({ bars, height = 420 }: Props) {
  return (
    <>
      {/* Desktop: full candlestick */}
      <div className="hidden md:block" style={{ height }}>
        <Candlestick bars={bars} />
      </div>
      {/* Mobile: simple area chart of closes */}
      <div className="block md:hidden" style={{ height: Math.min(height, 280) }}>
        <MobileLineFallback bars={bars} />
      </div>
    </>
  );
}


function Candlestick({ bars }: { bars: OHLCVBar[] }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    const chart = createChart(containerRef.current, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "rgba(0,0,0,0)" },
        textColor: "rgb(100, 116, 139)", // text-muted-ish
        fontSize: 11,
      },
      grid: {
        horzLines: { color: "rgba(148, 163, 184, 0.2)" },
        vertLines: { color: "rgba(148, 163, 184, 0.1)" },
      },
      rightPriceScale: { borderVisible: false },
      timeScale: {
        borderVisible: false,
        timeVisible: false,
        secondsVisible: false,
      },
      crosshair: {
        vertLine: { color: "rgba(79, 70, 229, 0.4)", labelBackgroundColor: "rgb(79, 70, 229)" },
        horzLine: { color: "rgba(79, 70, 229, 0.4)", labelBackgroundColor: "rgb(79, 70, 229)" },
      },
    });
    const series = chart.addSeries(CandlestickSeries, {
      upColor: "rgb(16, 185, 129)",
      downColor: "rgb(239, 68, 68)",
      borderUpColor: "rgb(16, 185, 129)",
      borderDownColor: "rgb(239, 68, 68)",
      wickUpColor: "rgb(16, 185, 129)",
      wickDownColor: "rgb(239, 68, 68)",
    });
    chartRef.current = chart;
    seriesRef.current = series;

    return () => {
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, []);

  // Push fresh data whenever the bars prop changes (range switch, ticker change).
  // Daily bars use the YYYY-MM-DD prefix as a business-day string so the chart
  // shows the calendar date regardless of viewer timezone. Parsing the ISO
  // datetime via `new Date(...)` was reinterpreting midnight UTC as midnight
  // local, which shifted every candle one day backwards in UTC+ timezones.
  useEffect(() => {
    if (!seriesRef.current) return;
    const data = bars.map((b) => ({
      time: b.date.slice(0, 10) as Time,
      open: b.open,
      high: b.high,
      low: b.low,
      close: b.close,
    }));
    seriesRef.current.setData(data);
    chartRef.current?.timeScale().fitContent();
  }, [bars]);

  return <div ref={containerRef} className="h-full w-full" />;
}


function MobileLineFallback({ bars }: { bars: OHLCVBar[] }) {
  const data = useMemo(
    () => bars.map((b) => ({ date: b.date, close: b.close })),
    [bars],
  );

  return (
    <ResponsiveContainer width="100%" height="100%">
      <AreaChart data={data}>
        <defs>
          <linearGradient id="cs-mobile-grad" x1="0" y1="0" x2="0" y2="1">
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
          tickFormatter={(v) => `$${v.toFixed(0)}`}
          axisLine={false}
          tickLine={false}
          tick={{ fontSize: 10, fill: "rgb(var(--text-muted))" }}
          width={48}
          domain={["dataMin", "dataMax"]}
        />
        <Tooltip
          contentStyle={{
            borderRadius: 8,
            border: "1px solid rgb(var(--border))",
            fontSize: 12,
          }}
          formatter={(v: number) => [formatMoney(v, "USD"), "Close"]}
          labelFormatter={(d) => new Date(d).toLocaleDateString("en-US")}
        />
        <Area
          type="monotone"
          dataKey="close"
          stroke="rgb(79 70 229)"
          strokeWidth={2}
          fill="url(#cs-mobile-grad)"
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
