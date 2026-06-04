import { Navigate, Outlet, useLocation } from "react-router-dom";
import { selectIsAuthenticated, useAuthStore } from "@/store/authStore";

/**
 * Layout route that gates child routes behind authentication.
 * If `user` + `refreshToken` are both present in the store, render the nested route.
 * Otherwise redirect to /auth, preserving the original location so we can return
 * the user after they log in.
 */
export function ProtectedRoute() {
  const isAuthenticated = useAuthStore(selectIsAuthenticated);
  const location = useLocation();

  if (!isAuthenticated) {
    return <Navigate to="/auth" state={{ from: location }} replace />;
  }
  return <Outlet />;
}
