import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";
import type { Currency } from "@/lib/constants";

export interface AuthUser {
  id: string;
  email: string;
  full_name: string;
  base_currency: Currency;
  created_at: string;
}

interface AuthState {
  user: AuthUser | null;
  /** Short-lived (15 min). Lives in memory only — never persisted. */
  accessToken: string | null;
  /** Long-lived (7 days). Persisted to localStorage; rehydrated on reload.
   *  Anti-pattern note: localStorage tokens are vulnerable to XSS.
   *  Production should move this to an httpOnly cookie. */
  refreshToken: string | null;
  setAuth: (payload: { user: AuthUser; access_token: string; refresh_token: string }) => void;
  setAccessToken: (token: string) => void;
  setUser: (user: AuthUser) => void;
  clear: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      user: null,
      accessToken: null,
      refreshToken: null,
      setAuth: ({ user, access_token, refresh_token }) =>
        set({ user, accessToken: access_token, refreshToken: refresh_token }),
      setAccessToken: (token) => set({ accessToken: token }),
      setUser: (user) => set({ user }),
      clear: () => set({ user: null, accessToken: null, refreshToken: null }),
    }),
    {
      name: "lumen.auth",
      storage: createJSONStorage(() => localStorage),
      // Only persist the long-lived pieces. Access token is in-memory only.
      partialize: (state) => ({ user: state.user, refreshToken: state.refreshToken }),
    },
  ),
);

/** Selector helpers (keeps components from over-subscribing to the whole store). */
export const selectIsAuthenticated = (s: AuthState) => !!s.user && !!s.refreshToken;
