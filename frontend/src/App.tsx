import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "@/components/layout/AppShell";
import { ProtectedRoute } from "@/components/layout/ProtectedRoute";
import LandingPage from "@/pages/LandingPage";
import AuthPage from "@/pages/AuthPage";
import ForgotPasswordPage from "@/pages/ForgotPasswordPage";
import ResetPasswordPage from "@/pages/ResetPasswordPage";
import VerifyEmailPage from "@/pages/VerifyEmailPage";
import DashboardPage from "@/pages/DashboardPage";
import TransactionsPage from "@/pages/TransactionsPage";
import BudgetPage from "@/pages/BudgetPage";
import GoalsPage from "@/pages/GoalsPage";
import PlannedPage from "@/pages/RecurringPage";
import MarketsPage from "@/pages/MarketsPage";
import StockDetailPage from "@/pages/StockDetailPage";
import PortfolioPage from "@/pages/PortfolioPage";
import AlertsPage from "@/pages/AlertsPage";
import ReportsPage from "@/pages/ReportsPage";
import SettingsPage from "@/pages/SettingsPage";

export default function App() {
  return (
    <Routes>
      {/* Public routes */}
      <Route path="/" element={<LandingPage />} />
      <Route path="/auth" element={<AuthPage />} />
      <Route path="/auth/forgot" element={<ForgotPasswordPage />} />
      <Route path="/auth/reset" element={<ResetPasswordPage />} />
      <Route path="/auth/verify" element={<VerifyEmailPage />} />

      {/* Authenticated app — gated by ProtectedRoute, then wrapped in the canonical AppShell. */}
      <Route element={<ProtectedRoute />}>
        <Route element={<AppShell />}>
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/transactions" element={<TransactionsPage />} />
          <Route path="/budget" element={<BudgetPage />} />
          <Route path="/goals" element={<GoalsPage />} />
          <Route path="/planned" element={<PlannedPage />} />
          {/* Legacy path — keeps existing bookmarks working after the Recurring → Planned rename. */}
          <Route path="/recurring" element={<Navigate to="/planned" replace />} />
          <Route path="/markets" element={<MarketsPage />} />
          <Route path="/stocks/:ticker" element={<StockDetailPage />} />
          <Route path="/portfolio" element={<PortfolioPage />} />
          {/* Legacy paths — Net Worth page was removed; old bookmarks land on the dashboard. */}
          <Route path="/accounts" element={<Navigate to="/dashboard" replace />} />
          <Route path="/networth" element={<Navigate to="/dashboard" replace />} />
          <Route path="/alerts" element={<AlertsPage />} />
          <Route path="/reports" element={<ReportsPage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Route>
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
