import { useCurrency } from "@/hooks/useCurrency";
import { useFxRate } from "@/hooks/useFxRate";
import { formatMoney } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { Currency } from "@/lib/constants";

interface MoneyWithBaseProps {
  amount: number;
  /** The native currency of the amount (e.g. "USD" for portfolio values). */
  currency: Currency;
  /** Inline (default) renders "€Y · $X" on one line (base primary +
   *  native after the dot). Block renders the native amount on a smaller
   *  muted line below the base-currency primary — used in table cells
   *  and KPI values where vertical space allows. */
  variant?: "inline" | "block";
  /** When provided, overrides `useCurrency()` — handy for previewing values
   *  in a currency other than the user's base (e.g. a "preview in USD" toggle). */
  baseOverride?: Currency;
  /** Pass-through `formatMoney` options. */
  signed?: boolean;
  digits?: number;
  className?: string;
}

/**
 * Renders a money value with the user's selected base currency as the
 * primary number and the native currency as a small subline when the two
 * differ. Matches the "Goals convention" used by GoalAmountDisplay /
 * RecurringPage / TransactionsPage — base currency is what the user
 * picked in the topbar, so it goes first; native (USD for portfolio,
 * the row's own currency elsewhere) is the reference, in the subline.
 *
 * Falls back to just the native amount if the FX rate hasn't loaded yet
 * (avoids a layout flash on first paint) or if native === base.
 */
export function MoneyWithBase({
  amount,
  currency,
  variant = "inline",
  baseOverride,
  signed,
  digits,
  className,
}: MoneyWithBaseProps) {
  const userBase = useCurrency();
  const base = baseOverride ?? userBase;
  const rate = useFxRate(currency, base);

  // Same currency, or rate hasn't arrived yet — render just the native value.
  if (currency === base || rate == null) {
    const single = formatMoney(amount, currency, {
      signed,
      maximumFractionDigits: digits,
      minimumFractionDigits: digits,
    });
    return <span className={className}>{single}</span>;
  }

  // Different currency: primary in BASE (converted), subline in NATIVE.
  const primary = formatMoney(amount * rate, base, {
    signed,
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  });
  const native = formatMoney(amount, currency, {
    signed: false,
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  });

  if (variant === "block") {
    return (
      <span className={cn("inline-flex flex-col items-end leading-tight", className)}>
        <span>{primary}</span>
        <span className="text-uppercase-label text-text-muted">{native}</span>
      </span>
    );
  }

  return (
    <span className={className}>
      {primary}{" "}
      <span className="text-text-muted">· {native}</span>
    </span>
  );
}

/**
 * String-only variant of the same idea — for places that can't render JSX
 * (e.g. Recharts tooltip formatters, KPI `value` strings). When native ===
 * base or no FX rate is available, returns the single native amount.
 * Otherwise returns "€Y · $X" — base primary, native after the dot —
 * matching the JSX component's Goals convention.
 */
export function formatMoneyWithBase(
  amount: number,
  currency: Currency,
  base: Currency,
  rate: number | null,
  opts?: { signed?: boolean; digits?: number },
): string {
  if (currency === base || rate == null) {
    return formatMoney(amount, currency, {
      signed: opts?.signed,
      maximumFractionDigits: opts?.digits,
      minimumFractionDigits: opts?.digits,
    });
  }
  const primary = formatMoney(amount * rate, base, {
    signed: opts?.signed,
    maximumFractionDigits: opts?.digits,
    minimumFractionDigits: opts?.digits,
  });
  const native = formatMoney(amount, currency, {
    maximumFractionDigits: opts?.digits,
    minimumFractionDigits: opts?.digits,
  });
  return `${primary} · ${native}`;
}
