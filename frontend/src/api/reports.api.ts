import { apiClient } from "./client";

export interface SpendingItem {
  category_id: string | null;
  category_name: string;
  color: string;
  total: number;
  count: number;
  pct: number;
}

export interface SpendingReport {
  from: string | null;
  to: string | null;
  total_expense: number;
  total_income: number;
  items: SpendingItem[];
}

export interface MonthlyRow {
  year: number;
  month: number;
  income: number;
  expense: number;
  savings_rate: number;
}

export interface MonthlyReport {
  months: MonthlyRow[];
}

export async function getSpendingReport(from?: string, to?: string): Promise<SpendingReport> {
  const params: Record<string, string> = {};
  if (from) params.from = from;
  if (to) params.to = to;
  const res = await apiClient.get<SpendingReport>("/reports/spending", { params });
  return res.data;
}

export async function getMonthlyReport(
  months = 6,
  end?: string,
): Promise<MonthlyReport> {
  const params: Record<string, string | number> = { months };
  // `end` is "YYYY-MM" — anchors the returned window to the given month
  // (inclusive). Omit for the default "ending at current month" behaviour.
  if (end) params.end = end;
  const res = await apiClient.get<MonthlyReport>("/reports/monthly", { params });
  return res.data;
}

export interface MerchantRow {
  merchant: string;
  category_name: string;
  count: number;
  total: number;
  avg: number;
}

export interface TopMerchantsReport {
  from: string | null;
  to: string | null;
  items: MerchantRow[];
}

export async function getTopMerchants(
  from?: string,
  to?: string,
  limit = 10,
): Promise<TopMerchantsReport> {
  const params: Record<string, string | number> = { limit };
  if (from) params.from = from;
  if (to) params.to = to;
  const res = await apiClient.get<TopMerchantsReport>("/reports/merchants", { params });
  return res.data;
}
