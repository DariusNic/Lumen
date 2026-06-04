import type { Currency } from "./constants";

export function formatMoney(
  amount: number,
  currency: Currency,
  opts?: { signed?: boolean; minimumFractionDigits?: number; maximumFractionDigits?: number },
): string {
  const formatter = new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    minimumFractionDigits: opts?.minimumFractionDigits ?? 0,
    maximumFractionDigits: opts?.maximumFractionDigits ?? 2,
  });
  if (opts?.signed && amount > 0) return `+${formatter.format(amount)}`;
  return formatter.format(amount);
}

export function formatPercent(
  fraction: number,
  opts?: { signed?: boolean; digits?: number },
): string {
  const formatter = new Intl.NumberFormat("en-US", {
    style: "percent",
    minimumFractionDigits: opts?.digits ?? 0,
    maximumFractionDigits: opts?.digits ?? 1,
  });
  if (opts?.signed && fraction > 0) return `+${formatter.format(fraction)}`;
  return formatter.format(fraction);
}

export function formatCompactNumber(n: number): string {
  return new Intl.NumberFormat("en-US", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(n);
}

const TODAY = new Date();
const ONE_DAY = 24 * 60 * 60 * 1000;

export function formatDate(date: Date | string): string {
  const d = typeof date === "string" ? new Date(date) : date;
  const diff = Math.round((TODAY.setHours(0, 0, 0, 0) - new Date(d).setHours(0, 0, 0, 0)) / ONE_DAY);
  if (diff === 0) return "Today";
  if (diff === 1) return "Yesterday";
  if (diff > 1 && diff < 7) return d.toLocaleDateString("en-US", { weekday: "long" });
  return d.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: d.getFullYear() === new Date().getFullYear() ? undefined : "numeric",
  });
}
