import axios from "axios";
import { apiClient, API_BASE_URL } from "./client";
import type { AuthUser } from "@/store/authStore";
import type { Currency } from "@/lib/constants";

export interface RegisterPayload {
  email: string;
  password: string;
  full_name: string;
  base_currency: Currency;
}

export interface LoginPayload {
  email: string;
  password: string;
}

export interface AuthSuccess {
  user: AuthUser;
  access_token: string;
  refresh_token: string;
}

/** Production response shape from POST /api/auth/register. The server no
 * longer auto-issues JWTs — the user must verify their email first. */
export interface RegisterResponse {
  user: AuthUser;
  verification_required: true;
}

/** POST /api/auth/register — creates the account and emails a verification
 * link. Returns the public user (no tokens). The client should show a
 * "check your email" screen, not redirect to /dashboard. */
export async function register(payload: RegisterPayload): Promise<RegisterResponse> {
  const res = await apiClient.post<RegisterResponse>("/auth/register", payload);
  return res.data;
}

/** POST /api/auth/login — returns 403 EMAIL_NOT_VERIFIED if the account
 * hasn't confirmed yet. Callers should distinguish that case. */
export async function login(payload: LoginPayload): Promise<AuthSuccess> {
  const res = await apiClient.post<AuthSuccess>("/auth/login", payload);
  return res.data;
}

/** POST /api/auth/logout — bare axios so the response interceptor doesn't try to refresh. */
export async function logout(accessToken: string): Promise<void> {
  await axios.post(`${API_BASE_URL}/auth/logout`, null, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

// --- Email verification ----------------------------------------------------

export interface VerifyEmailResponse {
  user: AuthUser;
}

/** POST /api/auth/verify-email — consumes the token from the email link. */
export async function verifyEmail(token: string): Promise<VerifyEmailResponse> {
  const res = await apiClient.post<VerifyEmailResponse>("/auth/verify-email", { token });
  return res.data;
}

/** POST /api/auth/resend-verification — always 200 (no enumeration leak). */
export async function resendVerification(email: string): Promise<void> {
  await apiClient.post("/auth/resend-verification", { email });
}

// --- Password reset --------------------------------------------------------

export interface ForgotPayload {
  email: string;
}

export interface ResetPayload {
  token: string;
  password: string;
}

/** POST /api/auth/forgot — always 200 regardless of whether the email is
 * registered (anti-enumeration). */
export async function forgot(payload: ForgotPayload): Promise<void> {
  await apiClient.post("/auth/forgot", payload);
}

/** POST /api/auth/reset — 422 with a clear message if the token is bad. */
export async function reset(payload: ResetPayload): Promise<void> {
  await apiClient.post("/auth/reset", payload);
}
