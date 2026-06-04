import { apiClient } from "./client";

export type AlertSeverity = "critical" | "warning" | "info";
export type AlertGroup = "Today" | "Yesterday" | "This week" | "Earlier";
export type AlertIcon =
  | "pie-chart"
  | "alert-triangle"
  | "trending-up"
  | "trending-down"
  | "flag"
  | "repeat"
  | "calendar"
  | "wallet";
export type AlertSource =
  | "budget_overrun"
  | "goal_behind"
  | "recurring_due"
  | "stale_account"
  | "signal_change";

export interface Alert {
  id: string;
  severity: AlertSeverity;
  icon: AlertIcon;
  title: string;
  message: string;
  timestamp: string;
  group: AlertGroup;
  unread: boolean;
  link: string;
  source: AlertSource;
}

export interface AlertList {
  alerts: Alert[];
  unread_count: number;
}

export async function listAlerts(): Promise<AlertList> {
  const res = await apiClient.get<AlertList>("/alerts");
  return res.data;
}

/** Pass `ids` to mark specific alerts; pass `[]` (or omit) to mark all. */
export async function markRead(ids?: string[]): Promise<{ ok: boolean; marked: number }> {
  const res = await apiClient.post<{ ok: boolean; marked: number }>(
    "/alerts/read",
    { ids: ids ?? [] },
  );
  return res.data;
}
