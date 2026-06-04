import axios, {
  AxiosError,
  type AxiosRequestConfig,
  type InternalAxiosRequestConfig,
} from "axios";
import { useAuthStore } from "@/store/authStore";

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api";

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: { "Content-Type": "application/json" },
});

// Pull the `exp` (seconds since epoch) out of a JWT without verifying it.
// Server still validates — this is purely a client-side hint to decide whether
// to refresh proactively. Returns null on any parse/decode failure so callers
// fall back to the existing 401-retry path.
function jwtExpiresAtMs(token: string): number | null {
  try {
    const payload = token.split(".")[1];
    if (!payload) return null;
    const padded = payload.padEnd(payload.length + ((4 - (payload.length % 4)) % 4), "=");
    const decoded = JSON.parse(atob(padded.replace(/-/g, "+").replace(/_/g, "/")));
    return typeof decoded.exp === "number" ? decoded.exp * 1000 : null;
  } catch {
    return null;
  }
}

// Mid-session expiry guard: treat a token that expires within 30s as already
// gone. The response-side 401 interceptor still catches actual 401s, but
// this avoids them whenever we can predict expiry from the JWT's `exp`.
const PROACTIVE_REFRESH_MARGIN_MS = 30_000;

// --- Request: attach the access token if we have one --------------------------------
// Proactive refresh: if we have a refreshToken but no accessToken (e.g. after a
// page reload — refresh is persisted to localStorage, access is memory-only) OR
// if the in-memory accessToken is about to expire, kick off a refresh BEFORE
// the first request so the page does not show a 401-storm in devtools while
// every query fails and retries. Concurrent requests park on `waiters`.
apiClient.interceptors.request.use(async (config) => {
  let access = useAuthStore.getState().accessToken;
  const refresh = useAuthStore.getState().refreshToken;
  const expiringSoon =
    access != null &&
    (() => {
      const expMs = jwtExpiresAtMs(access);
      return expMs != null && expMs - Date.now() < PROACTIVE_REFRESH_MARGIN_MS;
    })();
  const needsRefresh = (!access || expiringSoon) && !!refresh;
  if (needsRefresh && !(config as RetryConfig)._skipProactiveRefresh) {
    access = await ensureAccessToken(refresh!);
  }
  if (access) {
    config.headers.Authorization = `Bearer ${access}`;
  }
  return config;
});

// --- Response: on 401, refresh once and retry ---------------------------------------
type RetryConfig = InternalAxiosRequestConfig & {
  _retry?: boolean;
  _skipProactiveRefresh?: boolean;
};

let isRefreshing = false;
let waiters: Array<(token: string | null) => void> = [];

/** Single-flight refresh used by the proactive request-side hook. Concurrent
 * callers park on the same `waiters` list the response interceptor uses, so
 * we never fire `/auth/refresh` more than once at a time. */
async function ensureAccessToken(refreshToken: string): Promise<string | null> {
  if (isRefreshing) {
    return new Promise<string | null>((resolve) => {
      waiters.push((token) => resolve(token));
    });
  }
  isRefreshing = true;
  try {
    const newToken = await refreshAccessToken(refreshToken);
    useAuthStore.getState().setAccessToken(newToken);
    waiters.forEach((w) => w(newToken));
    waiters = [];
    return newToken;
  } catch {
    waiters.forEach((w) => w(null));
    waiters = [];
    useAuthStore.getState().clear();
    return null;
  } finally {
    isRefreshing = false;
  }
}

apiClient.interceptors.response.use(
  (res) => res,
  async (error: AxiosError) => {
    const original = error.config as RetryConfig | undefined;
    if (!original || error.response?.status !== 401 || original._retry) {
      return Promise.reject(error);
    }

    const { refreshToken } = useAuthStore.getState();
    if (!refreshToken) {
      return Promise.reject(error);
    }

    original._retry = true;

    if (isRefreshing) {
      // Park this request until the in-flight refresh completes.
      return new Promise((resolve, reject) => {
        waiters.push((newToken) => {
          if (!newToken) return reject(error);
          original.headers.Authorization = `Bearer ${newToken}`;
          apiClient(original).then(resolve).catch(reject);
        });
      });
    }

    isRefreshing = true;
    try {
      const newToken = await refreshAccessToken(refreshToken);
      useAuthStore.getState().setAccessToken(newToken);
      waiters.forEach((w) => w(newToken));
      waiters = [];
      original.headers.Authorization = `Bearer ${newToken}`;
      return apiClient(original);
    } catch (refreshErr) {
      waiters.forEach((w) => w(null));
      waiters = [];
      useAuthStore.getState().clear();
      return Promise.reject(refreshErr);
    } finally {
      isRefreshing = false;
    }
  },
);

/** Bare axios call — does NOT go through the interceptor (avoids recursion on 401). */
async function refreshAccessToken(refreshToken: string): Promise<string> {
  const res = await axios.post<{ access_token: string }>(
    `${API_BASE_URL}/auth/refresh`,
    null,
    { headers: { Authorization: `Bearer ${refreshToken}` } },
  );
  return res.data.access_token;
}

/** Pull the human-readable message out of our `{error_code, message, details}` envelope. */
export function parseApiError(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const data = err.response?.data as { message?: string } | undefined;
    if (data?.message) return data.message;
    if (err.message) return err.message;
  }
  return "Something went wrong. Please try again.";
}

/** Re-export so other modules don't import axios directly for types. */
export type { AxiosRequestConfig };
