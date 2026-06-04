import { cn } from "@/lib/utils";

export type Signal = "BUY" | "HOLD" | "SELL";

const toneFor = (signal: Signal) => {
  switch (signal) {
    case "BUY":
      return "bg-success/10 text-success border-success/20";
    case "SELL":
      return "bg-danger/10 text-danger border-danger/20";
    default:
      return "bg-surface-variant text-text-muted border-border";
  }
};

interface SignalPillProps {
  signal: Signal;
  confidence?: number;
  className?: string;
}

export function SignalPill({ signal, confidence, className }: SignalPillProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-uppercase-label uppercase",
        toneFor(signal),
        className,
      )}
    >
      <span className="font-semibold tracking-wider">{signal}</span>
      {typeof confidence === "number" && (
        <span className="tabular text-[10px] opacity-80">
          {Math.round(confidence * 100)}%
        </span>
      )}
    </span>
  );
}

interface SignalBadgeProps {
  signal: Signal;
  confidence?: number;
  className?: string;
}

/** Larger card-sized signal badge used on the Stock Detail page. */
export function SignalBadge({ signal, confidence, className }: SignalBadgeProps) {
  const tone = toneFor(signal);
  return (
    <div
      className={cn(
        "flex flex-col items-center gap-1 rounded-xl border px-lg py-md",
        tone,
        className,
      )}
    >
      <span className="text-h2 font-h2 leading-none tracking-tight">{signal}</span>
      {typeof confidence === "number" && (
        <span className="text-body-small tabular opacity-80">
          {Math.round(confidence * 100)}% confidence
        </span>
      )}
    </div>
  );
}
