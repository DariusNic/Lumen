import { formatMoney } from "@/lib/format";
import { useCurrency } from "@/hooks/useCurrency";
import { useFxRate } from "@/hooks/useFxRate";
import { cn } from "@/lib/utils";
import type { Currency } from "@/lib/constants";

interface GoalLike {
  saved_amount: number;
  target_amount: number;
  currency: Currency;
}

interface Props {
  goal: GoalLike;
  /** `compact` strips the subline padding for the small dashboard card.
   *  The native-currency subline still renders if the goal is in a
   *  different currency than the user's base. */
  compact?: boolean;
  className?: string;
}

/**
 * Render a goal's progress as "<saved> / <target>" in the user's
 * currently-selected base currency, with a small subline showing the
 * native-currency amounts when the goal was created in a different
 * currency than the user's base.
 *
 * Examples (user base = RON):
 *   - Goal in RON  → "RON 150 / RON 50,000" (no subline)
 *   - Goal in EUR  → primary "RON 5,580 / RON 1,860,000"
 *                    subline "€1,200 / €400,000"
 *
 * Falls back to native-only when the FX rate hasn't loaded yet, so the
 * card never shows a blank or partially-converted value during a refetch.
 */
export function GoalAmountDisplay({ goal, compact, className }: Props) {
  const baseCurrency = useCurrency();
  const rate = useFxRate(goal.currency, baseCurrency);

  const sameCurrency = goal.currency === baseCurrency;
  // While the FX rate is loading and the goal is in a foreign currency,
  // fall back to native-only display rather than rendering ambiguous
  // mid-conversion numbers.
  if (sameCurrency || rate == null) {
    return (
      <div className={cn("tabular text-text-primary", className)}>
        {formatMoney(goal.saved_amount, goal.currency, { maximumFractionDigits: 0 })}{" / "}
        {formatMoney(goal.target_amount, goal.currency, { maximumFractionDigits: 0 })}
      </div>
    );
  }

  const savedBase = goal.saved_amount * rate;
  const targetBase = goal.target_amount * rate;

  return (
    <div className={cn(className)}>
      <div className="tabular text-text-primary">
        {formatMoney(savedBase, baseCurrency, { maximumFractionDigits: 0 })}{" / "}
        {formatMoney(targetBase, baseCurrency, { maximumFractionDigits: 0 })}
      </div>
      <div
        className={cn(
          "tabular text-uppercase-label uppercase text-text-muted",
          compact ? "mt-0.5" : "mt-1",
        )}
      >
        {formatMoney(goal.saved_amount, goal.currency, { maximumFractionDigits: 0 })}{" / "}
        {formatMoney(goal.target_amount, goal.currency, { maximumFractionDigits: 0 })}
      </div>
    </div>
  );
}
