import { apiClient } from "./client";
import type { AuthUser } from "@/store/authStore";
import type { Currency } from "@/lib/constants";

export interface UpdateMePayload {
  full_name?: string;
  base_currency?: Currency;
}

interface MeResponse {
  user: AuthUser;
}

/** GET /api/me */
export async function getMe(): Promise<AuthUser> {
  const res = await apiClient.get<MeResponse>("/me");
  return res.data.user;
}

/** PATCH /api/me */
export async function updateMe(payload: UpdateMePayload): Promise<AuthUser> {
  const res = await apiClient.patch<MeResponse>("/me", payload);
  return res.data.user;
}
