import { apiClient } from "./client";
import type { Currency } from "@/lib/constants";

/** "once" = one-off planned payment (wedding, tax bill); the others repeat. */
export type Frequency = "once" | "weekly" | "biweekly" | "monthly" | "yearly";

/** Detection only ever produces non-"once" patterns (clusters need ≥ 2 occurrences). */
export type DetectedFrequency = "weekly" | "biweekly" | "monthly" | "yearly";

export type RecurringStatus = "active" | "paused" | "completed";

export interface RecurringPayment {
  id: string;
  name: string;
  merchant_pattern: string;
  amount: number;
  /** `amount` converted to the user's base currency at today's FX rate.
   *  `null` when FX is unavailable — callers should fall back to `amount`. */
  amount_base: number | null;
  currency: Currency;
  frequency: Frequency;
  start_date: string;
  end_date: string | null;
  category_id: string | null;
  category_name: string | null;
  /** Present when this recurring drives a goal's monthly auto-contribute.
   *  Frontend uses the flag to render "Goal contribution" instead of the
   *  internal `GOAL:<oid>` merchant pattern. */
  goal_id: string | null;
  is_income: boolean;
  auto_create_transaction: boolean;
  status: RecurringStatus;
  next_due: string;
  created_at: string;
}

export interface RecurringCreatePayload {
  name: string;
  merchant_pattern: string;
  amount: number;
  currency: Currency;
  frequency: Frequency;
  start_date: string;
  end_date?: string;
  category_id?: string;
  is_income?: boolean;
  auto_create_transaction?: boolean;
}

export interface RecurringUpdatePayload {
  name?: string;
  merchant_pattern?: string;
  amount?: number;
  currency?: Currency;
  frequency?: Frequency;
  start_date?: string;
  end_date?: string | null;
  category_id?: string;
  is_income?: boolean;
  auto_create_transaction?: boolean;
  status?: RecurringStatus;
}

export interface DetectionSuggestion {
  merchant_pattern: string;
  average_amount: number;
  currency: Currency;
  frequency: DetectedFrequency;
  occurrences: number;
  last_seen: string;
  is_income: boolean;
  sample_descriptions: string[];
}

export interface DetectionResult {
  suggestions: DetectionSuggestion[];
  transactions_scanned: number;
  clusters_found: number;
}

export interface CalendarResponse {
  year: number;
  month: number;
  by_day: Record<string, RecurringPayment[]>;
}

export async function listRecurring(): Promise<RecurringPayment[]> {
  const res = await apiClient.get<{ recurring: RecurringPayment[] }>("/recurring");
  return res.data.recurring;
}

export async function createRecurring(
  payload: RecurringCreatePayload,
): Promise<RecurringPayment> {
  const res = await apiClient.post<{ recurring: RecurringPayment }>("/recurring", payload);
  return res.data.recurring;
}

export async function updateRecurring(
  id: string,
  payload: RecurringUpdatePayload,
): Promise<RecurringPayment> {
  const res = await apiClient.patch<{ recurring: RecurringPayment }>(
    `/recurring/${id}`,
    payload,
  );
  return res.data.recurring;
}

export async function deleteRecurring(id: string): Promise<void> {
  await apiClient.delete(`/recurring/${id}`);
}

/** "I paid this" — creates the transaction for the current cycle and
 *  rolls `next_due` forward by one frequency step. Use when the recurring
 *  has `auto_create_transaction=false` and the user just paid out-of-band
 *  (e.g. bank transfer for rent). */
export async function markPaid(id: string): Promise<RecurringPayment> {
  const res = await apiClient.post<{ recurring: RecurringPayment }>(
    `/recurring/${id}/mark-paid`,
  );
  return res.data.recurring;
}

export async function getCalendar(year: number, month: number): Promise<CalendarResponse> {
  const res = await apiClient.get<CalendarResponse>("/recurring/calendar", {
    params: { year, month },
  });
  return res.data;
}

export async function detectRecurring(): Promise<DetectionResult> {
  const res = await apiClient.post<DetectionResult>("/recurring/detect");
  return res.data;
}
