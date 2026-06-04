import {
  LayoutDashboard,
  Receipt,
  PieChart,
  Flag,
  Repeat,
  LineChart,
  Briefcase,
  Bell,
  BarChart3,
  Settings,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  label: string;
  href: string;
  icon: LucideIcon;
  group: "overview" | "spending" | "investing" | "system";
}

/**
 * Canonical sidebar nav. Used by every authenticated page.
 * Order, grouping, and labels must stay identical across pages
 * — UX consistency overrides per-screen design variants.
 */
export const NAV_ITEMS: NavItem[] = [
  { label: "Dashboard", href: "/dashboard", icon: LayoutDashboard, group: "overview" },

  { label: "Transactions", href: "/transactions", icon: Receipt, group: "spending" },
  { label: "Budget", href: "/budget", icon: PieChart, group: "spending" },
  { label: "Goals", href: "/goals", icon: Flag, group: "spending" },
  { label: "Planned", href: "/planned", icon: Repeat, group: "spending" },

  { label: "Markets", href: "/markets", icon: LineChart, group: "investing" },
  { label: "Portfolio", href: "/portfolio", icon: Briefcase, group: "investing" },

  { label: "Alerts", href: "/alerts", icon: Bell, group: "system" },
  { label: "Reports", href: "/reports", icon: BarChart3, group: "system" },
  { label: "Settings", href: "/settings", icon: Settings, group: "system" },
];

export const NAV_GROUPS: { id: NavItem["group"]; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "spending", label: "Spending" },
  { id: "investing", label: "Investing" },
  { id: "system", label: "System" },
];
