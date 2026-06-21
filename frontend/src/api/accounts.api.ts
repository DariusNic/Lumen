import { apiClient } from "./client";
import type { Currency } from "@/lib/constants";

export type AccountType =
  | "cash"
  | "savings"
  | "investment"
  | "real_estate"
  | "vehicle"
  | "other_asset"
  | "credit"
  | "loan"
  | "mortgage"
  | "other_liability";

export interface Account {
  id: string;
  name: string;
  type: AccountType;
  category: "asset" | "liability";
  balance: number;
  currency: Currency;
  is_automatic: boolean;
  source_ref: string | null;
  notes: string | null;
  last_updated: string;
  created_at: string;
}

export interface AccountTotals {
  assets: number;
  liabilities: number;
  net_worth: number;
  /** All three figures are summed in this currency via daily ECB rates. */
  base_currency: Currency;
  /** True if FX conversion failed for at least one account (live API down +
   *  cache > 7 days old). The UI shows a small notice and treats face values
   *  as approximate when this is set. */
  mixed_currency: boolean;
}

export interface AccountsListResponse {
  accounts: Account[];
  totals: AccountTotals;
}

export async function listAccounts(): Promise<AccountsListResponse> {
  const res = await apiClient.get<AccountsListResponse>("/accounts");
  return res.data;
}
