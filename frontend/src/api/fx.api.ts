import { apiClient } from "./client";
import type { Currency } from "@/lib/constants";

export interface FxConvertResponse {
  from: Currency;
  to: Currency;
  amount: number;
  converted: number;
  rate: number;
  /** ISO date (YYYY-MM-DD) of the ECB rate used. */
  on: string;
}

export async function convert(
  from: Currency,
  to: Currency,
  amount: number,
  on?: string,
): Promise<FxConvertResponse> {
  const res = await apiClient.get<FxConvertResponse>("/fx/convert", {
    params: { from, to, amount, ...(on ? { on } : {}) },
  });
  return res.data;
}
