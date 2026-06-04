import { apiClient } from "./client";
import type { Currency } from "@/lib/constants";

export type HistoryRange = "1M" | "3M" | "6M" | "1Y" | "ALL";

export interface AccountBreakdownEntry {
  account_id: string;
  name: string;
  type: string;
  category: "asset" | "liability";
  balance_base: number;
}

export interface NetWorthCurrent {
  total_assets: number;
  total_liabilities: number;
  net_worth: number;
  base_currency: Currency;
  breakdown: AccountBreakdownEntry[];
  delta_30d: number | null;
  delta_30d_pct: number | null;
  last_snapshot_date: string | null;
  snapshot_count: number;
}

export interface NetWorthHistoryPoint {
  date: string;
  total_assets: number;
  total_liabilities: number;
  net_worth: number;
}

export interface NetWorthHistory {
  range: HistoryRange;
  points: NetWorthHistoryPoint[];
  base_currency: Currency;
}

export interface NetWorthSnapshot extends NetWorthHistoryPoint {
  id: string;
  base_currency: Currency;
  breakdown: AccountBreakdownEntry[];
  source: "scheduled_daily" | "manual" | "backfill" | "on_transaction";
}

export async function getCurrent(): Promise<NetWorthCurrent> {
  const res = await apiClient.get<NetWorthCurrent>("/networth");
  return res.data;
}

export async function getHistory(range: HistoryRange = "3M"): Promise<NetWorthHistory> {
  const res = await apiClient.get<NetWorthHistory>("/networth/history", { params: { range } });
  return res.data;
}

export async function takeSnapshot(): Promise<NetWorthSnapshot> {
  const res = await apiClient.post<{ snapshot: NetWorthSnapshot }>("/networth/snapshot");
  return res.data.snapshot;
}
