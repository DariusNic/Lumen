import { useAuthStore } from "@/store/authStore";
import { DEFAULT_BASE_CURRENCY, type Currency } from "@/lib/constants";

/**
 * Single source of truth for the user's base currency.
 *
 * Always reads from `authStore.user.base_currency` (the same value the backend
 * stores on the User record). Falls back to `DEFAULT_BASE_CURRENCY` for
 * unauthenticated routes (Landing, Auth) where no user is loaded yet.
 *
 * To **change** the currency, use `updateMe({ base_currency })` from
 * `@/api/me.api` and update the auth store with the returned user — this hook
 * re-renders automatically because it subscribes to the store slice.
 */
export function useCurrency(): Currency {
  return useAuthStore((s) => (s.user?.base_currency ?? DEFAULT_BASE_CURRENCY) as Currency);
}
