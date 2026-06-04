import { Area, AreaChart, ResponsiveContainer, Tooltip as ReTooltip, XAxis, YAxis } from "recharts";
import { Info, TrendingDown, TrendingUp, type LucideIcon } from "lucide-react";
import { useId } from "react";
import { cn } from "@/lib/utils";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

/** One point on a KPI mini-chart — label drives the X-axis tick + tooltip
 *  header, value drives the curve + Y-axis + tooltip body. */
export interface KpiSparkPoint {
  label: string;
  value: number;
}

interface KpiCardProps {
  label: string;
  value: string;
  /** Small muted second line below the main value — used to show the
   *  base-currency equivalent of a USD-anchored portfolio number
   *  (e.g. "$10,112.81" + "≈ €8,649"). Skip when value is already in base. */
  valueSubline?: string;
  delta?: { value: string; tone: "up" | "down" | "neutral" };
  icon?: LucideIcon;
  /** Time series for the mini-chart. Each point has a `label` (rendered as
   *  the X-axis tick and tooltip header — e.g. "Mar 26") and a `value`
   *  (the magnitude). Pass an empty array or single point to hide the chart. */
  spark?: KpiSparkPoint[];
  /** Used by both the Y-axis tick formatter and the tooltip body so the
   *  numbers are rendered consistently in the user's chosen currency. */
  sparkValueFormatter?: (v: number) => string;
  /** Thicker indigo accent stripe along the left edge (used for Net Worth). */
  accent?: boolean;
  /** Color hint for the spark line. Defaults to primary indigo. */
  sparkTone?: "primary" | "success" | "danger" | "neutral";
  /** One-line definition shown on hover/focus over a small info icon next
   *  to the label. Use to explain "what does this number mean?" — e.g.
   *  "Cash + Savings, today" for Total balance. */
  hint?: string;
  className?: string;
}

const TONE_RGB: Record<NonNullable<KpiCardProps["sparkTone"]>, string> = {
  primary: "rgb(79 70 229)",
  success: "rgb(16 185 129)",
  danger: "rgb(239 68 68)",
  neutral: "rgb(100 116 139)",
};

/** Compact Y-axis label — keeps the chart usable at narrow card widths.
 *  Drops the decimal once we reach hundreds-of-thousands so the label
 *  stays short ("-649k", 5 chars) instead of overflowing the axis gutter
 *  ("-649.4k", 7 chars, clips the leading minus when YAxis width is small). */
function defaultCompactNumber(v: number): string {
  const abs = Math.abs(v);
  if (abs >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (abs >= 100_000) return `${Math.round(v / 1_000)}k`;
  if (abs >= 1_000) return `${(v / 1_000).toFixed(1)}k`;
  return v.toFixed(0);
}

export function KpiCard({
  label,
  value,
  valueSubline,
  delta,
  icon: Icon,
  spark,
  sparkValueFormatter,
  accent,
  sparkTone = "primary",
  hint,
  className,
}: KpiCardProps) {
  const id = useId().replace(/:/g, "");
  const data = spark ?? [];
  const stroke = TONE_RGB[sparkTone];
  const hasTrend = data.length >= 2;
  const lastIndex = data.length - 1;

  // Y-axis label formatter: compact form ($X.Yk) so the tick labels fit
  // inside the small chart width without cluttering the card.
  const yTickFormatter = (v: number): string => {
    if (sparkValueFormatter) {
      // Compress the formatted value to its short form by stripping the
      // ".00" tail — keeps "$10k" instead of "$10,000.00" on the axis.
      return defaultCompactNumber(v);
    }
    return defaultCompactNumber(v);
  };

  return (
    <div
      className={cn(
        "group relative overflow-hidden rounded-xl border border-border bg-surface p-lg shadow-card",
        "transition-all duration-200 hover:-translate-y-0.5 hover:shadow-card-hover",
        accent && "before:absolute before:inset-y-0 before:left-0 before:w-1 before:bg-primary",
        className,
      )}
    >
      <div className="flex items-start justify-between gap-md">
        <span className="inline-flex items-center gap-1 text-uppercase-label uppercase text-text-muted">
          {label}
          {hint && (
            <TooltipProvider delayDuration={150}>
              <Tooltip>
                <TooltipTrigger asChild>
                  <button
                    type="button"
                    aria-label={`What does "${label}" mean?`}
                    className="rounded-full p-0.5 text-text-muted/60 transition-colors hover:text-primary focus-ring"
                  >
                    <Info className="h-3 w-3" />
                  </button>
                </TooltipTrigger>
                <TooltipContent side="top" className="max-w-[260px] text-balance">
                  {hint}
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          )}
        </span>
        {Icon && (
          <Icon className="h-4 w-4 text-text-muted transition-colors group-hover:text-primary" />
        )}
      </div>
      {/* Auto-fit: clamp keeps "€103,663.15" inside a 196 px KPI card at
          the xl breakpoint, where the IntelligencePanel squeezes the main
          column. Caps at ~1.5 rem on wide viewports for visual hierarchy.
          truncate + whitespace-nowrap are a safety belt — at extreme widths
          we'd rather show "…" than visually crop digits with overflow. */}
      <div
        className="mt-1.5 truncate font-h2 tabular text-text-primary leading-tight"
        style={{ fontSize: "clamp(1.0625rem, 1vw + 0.3rem, 1.5rem)" }}
        title={value}
      >
        {value}
      </div>
      {valueSubline && (
        <div
          className="mt-0.5 truncate text-uppercase-label uppercase text-text-muted tabular"
          title={valueSubline}
        >
          {valueSubline}
        </div>
      )}
      {delta && (
        <div
          className={cn(
            "mt-1 inline-flex items-center gap-1 text-body-small font-medium tabular",
            delta.tone === "up" && "text-success",
            delta.tone === "down" && "text-danger",
            delta.tone === "neutral" && "text-text-muted",
          )}
        >
          {delta.tone === "up" && <TrendingUp className="h-3.5 w-3.5" />}
          {delta.tone === "down" && <TrendingDown className="h-3.5 w-3.5" />}
          <span>{delta.value}</span>
        </div>
      )}

      {hasTrend ? (
        <div className="-mx-1 mt-md h-28">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 4 }}>
              <defs>
                <linearGradient id={`spark-${id}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={stroke} stopOpacity={0.28} />
                  <stop offset="70%" stopColor={stroke} stopOpacity={0.06} />
                  <stop offset="100%" stopColor={stroke} stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis
                dataKey="label"
                axisLine={false}
                tickLine={false}
                tick={{ fontSize: 10, fill: "rgb(var(--text-muted))" }}
                interval="preserveStartEnd"
                minTickGap={24}
                tickMargin={4}
              />
              {/* Y-axis pinned to a 0-baseline so all four KPI mini-charts line
                  up visually across the row. Trade-off: large-magnitude series
                  (e.g. Net worth at 100k) look flatter, but the row reads as
                  one coherent trend strip rather than four mismatched charts. */}
              <YAxis
                axisLine={false}
                tickLine={false}
                // Wide enough to fit "-649k" (5 chars at 10px ≈ 35px)
                // plus a little gutter; the old 36px clipped the leading
                // "-6" on Net Worth values in the hundreds of thousands.
                width={48}
                tick={{ fontSize: 10, fill: "rgb(var(--text-muted))" }}
                tickFormatter={yTickFormatter}
                // Let the axis include the actual data minimum (which can
                // be negative for cash flow / shifted net-worth) instead
                // of forcing the bottom to zero. With `[0, "dataMax"]`
                // and an all-negative series, the axis labels reverse
                // direction and the bottom-most tick can read confusingly
                // (e.g. a -649k value labelled "49.4k" when the leading
                // chars are clipped). `["dataMin", "dataMax"]` lets the
                // chart pick its natural bounds and the labels read
                // honestly top → bottom.
                domain={["dataMin", "dataMax"]}
                tickCount={3}
              />
              <ReTooltip
                cursor={{ stroke: "rgb(var(--border))", strokeWidth: 1, strokeDasharray: "3 3" }}
                contentStyle={{
                  borderRadius: 8,
                  border: "1px solid rgb(var(--border))",
                  fontSize: 12,
                  padding: "6px 10px",
                  boxShadow: "0 10px 24px rgba(15, 23, 42, 0.06)",
                }}
                labelStyle={{ color: "rgb(var(--text-muted))", marginBottom: 2 }}
                formatter={(v: number) => [
                  sparkValueFormatter ? sparkValueFormatter(v) : v.toLocaleString(),
                  // Strip the "· <month>" suffix so the tooltip body just
                  // shows the metric name (e.g. "Income"). The actual month
                  // being hovered is in the tooltip header above (the X-axis
                  // label), so repeating it — and worse, showing the
                  // currently-selected month for every hovered point —
                  // would be misleading.
                  label.split(" · ")[0],
                ]}
              />
              <Area
                // `monotone` instead of `natural`: both smooth the curve,
                // but `natural` is a cubic-spline that overshoots data
                // peaks. With `domain={[0, "dataMax"]}` and a peak that
                // sits at the very top of the Y range, the overshoot
                // renders ABOVE the plot area and gets clipped by the
                // SVG bounds — visible as a flat-topped curve. Monotone
                // smoothing strictly stays between adjacent data points,
                // so peaks land exactly at the Y-axis dataMax tick with
                // no clipping.
                type="monotone"
                dataKey="value"
                stroke={stroke}
                strokeWidth={2}
                strokeLinecap="round"
                strokeLinejoin="round"
                fill={`url(#spark-${id})`}
                isAnimationActive
                animationDuration={500}
                // Plot a single dot only at the latest point — current-value marker.
                // Recharts renders this output in a list, so each returned `<g>`
                // needs a stable `key` to silence the React warning.
                dot={(props: { cx?: number; cy?: number; index?: number }) => {
                  const { cx, cy, index } = props;
                  const k = `kpi-dot-${id}-${index ?? "x"}`;
                  if (cx == null || cy == null || index !== lastIndex) {
                    return <g key={k} />;
                  }
                  return (
                    <g key={k}>
                      <circle cx={cx} cy={cy} r={5} fill={stroke} fillOpacity={0.18} />
                      <circle cx={cx} cy={cy} r={3} fill={stroke} stroke="white" strokeWidth={1.5} />
                    </g>
                  );
                }}
                activeDot={{ r: 4, fill: stroke, stroke: "white", strokeWidth: 1.5 }}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      ) : data.length === 1 ? (
        <div className="mt-md text-uppercase-label uppercase text-text-muted">
          Trend appears once you have a few months of history
        </div>
      ) : null}
    </div>
  );
}
