import { useQuery } from "@tanstack/react-query";
import * as fxApi from "@/api/fx.api";
import { qk } from "@/lib/queryKeys";
import type { Currency } from "@/lib/constants";

/**
 * One-currency conversion rate. Returns the multiplier such that
 * `amount * rate` gives the value in `to` currency.
 *
 * Cached for 1 hour because ECB rates are daily; the refresh-FX-rates cron
 * fires at 17:00 UTC so the cached rate is stable across the working day.
 * Returns `null` while loading OR if the conversion is from a currency to
 * itself (so callers can skip rendering the conversion subline cleanly).
 */
export function useFxRate(from: Currency | string, to: Currency | string): number | null {
  const isIdentity = from === to;
  const { data } = useQuery({
    queryKey: qk.fx.rate(from, to),
    queryFn: () => fxApi.convert(from as Currency, to as Currency, 1),
    enabled: !isIdentity,
    staleTime: 60 * 60_000,
    gcTime: 24 * 60 * 60_000,
  });
  if (isIdentity) return 1;
  return data?.rate ?? null;
}
