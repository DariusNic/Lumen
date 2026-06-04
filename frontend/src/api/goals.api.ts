import { apiClient } from "./client";
import type { Currency } from "@/lib/constants";

export type GoalType = "travel" | "home" | "emergency" | "education" | "vehicle" | "other";
export type GoalStatus = "on-track" | "behind" | "ahead" | "completed";

/** Read-side summary of the active recurring auto-contribute (if any).
 *  Present on Goal when the backend finds a linked recurring_payment. */
export interface AutoContributeInfo {
  amount: number;
  /** ISO datetime of the next scheduled firing. */
  next_due: string;
  recurring_id: string;
}

export interface Goal {
  id: string;
  name: string;
  target_amount: number;
  saved_amount: number;
  currency: Currency;
  target_date: string;
  type: GoalType;
  priority: number;
  progress_pct: number;
  monthly_simple: number;
  months_remaining: number;
  status: GoalStatus;
  auto_contribute: AutoContributeInfo | null;
  created_at: string;
}

export interface GoalAutoContributeSetup {
  amount: number;
  /** ISO datetime — the first scheduled firing. */
  start_date: string;
}

export interface GoalCreatePayload {
  name: string;
  target_amount: number;
  currency: Currency;
  target_date: string;
  type?: GoalType;
  priority?: number;
  initial_deposit?: number;
  auto_contribute?: GoalAutoContributeSetup;
}

export interface GoalUpdatePayload {
  name?: string;
  target_amount?: number;
  target_date?: string;
  type?: GoalType;
  priority?: number;
  /** Tri-state:
   *   omitted   → no change to the linked auto-contribute schedule
   *   {amount, start_date} → upsert (create if missing, otherwise update);
   *                          next_due is always re-snapped server-side to
   *                          the first occurrence in the next calendar month
   *   false     → disable: soft-delete the linked recurring */
  auto_contribute?: GoalAutoContributeSetup | false;
}

export interface GoalContributePayload {
  amount: number;
  when?: string;
}

export async function listGoals(): Promise<Goal[]> {
  const res = await apiClient.get<{ goals: Goal[] }>("/goals");
  return res.data.goals;
}

export async function getGoal(id: string): Promise<Goal> {
  const res = await apiClient.get<{ goal: Goal }>(`/goals/${id}`);
  return res.data.goal;
}

export async function createGoal(payload: GoalCreatePayload): Promise<Goal> {
  const res = await apiClient.post<{ goal: Goal }>("/goals", payload);
  return res.data.goal;
}

export async function updateGoal(id: string, payload: GoalUpdatePayload): Promise<Goal> {
  const res = await apiClient.patch<{ goal: Goal }>(`/goals/${id}`, payload);
  return res.data.goal;
}

export async function deleteGoal(id: string): Promise<void> {
  await apiClient.delete(`/goals/${id}`);
}

export async function contributeToGoal(
  id: string,
  payload: GoalContributePayload,
): Promise<Goal> {
  const res = await apiClient.post<{ goal: Goal }>(`/goals/${id}/contribute`, payload);
  return res.data.goal;
}
