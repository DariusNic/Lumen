import { ChevronDown, Loader2, Menu, PanelRight, Search } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { useCurrency } from "@/hooks/useCurrency";
import { useAuthStore } from "@/store/authStore";
import { SUPPORTED_CURRENCIES, type Currency } from "@/lib/constants";
import { Sheet, SheetContent, SheetDescription, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { Sidebar } from "./Sidebar";
import { IntelligencePanel } from "./IntelligencePanel";
import { SearchPalette } from "./SearchPalette";
import { AlertsPopover } from "./AlertsPopover";
import { useEffect, useState } from "react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import * as meApi from "@/api/me.api";

export function Topbar() {
  const currency = useCurrency();
  const setUser = useAuthStore((s) => s.setUser);
  const qc = useQueryClient();
  const [leftOpen, setLeftOpen] = useState(false);
  const [rightOpen, setRightOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);

  // Cmd/Ctrl-K opens the search palette anywhere in the app.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setSearchOpen((v) => !v);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const currencyMutation = useMutation({
    mutationFn: (next: Currency) => meApi.updateMe({ base_currency: next }),
    onSuccess: (user) => {
      setUser(user);
      // Base currency change rewrites amount_base on the backend (transactions
      // re-converted at historical rates, budgets re-converted at today's rate,
      // Net cash flow account re-stamped). Every query that displays money
      // needs to refetch. Cheapest correct option is a global invalidation.
      qc.invalidateQueries();
    },
  });

  return (
    <header className="sticky top-0 z-30 flex h-16 shrink-0 items-center gap-md border-b border-border bg-surface/90 px-md backdrop-blur-md md:px-lg">
      {/* Mobile: hamburger that opens the sidebar drawer */}
      <Sheet open={leftOpen} onOpenChange={setLeftOpen}>
        <SheetTrigger asChild>
          <Button
            variant="ghost"
            size="icon"
            className="md:hidden"
            aria-label="Open navigation"
          >
            <Menu className="h-5 w-5" />
          </Button>
        </SheetTrigger>
        <SheetContent side="left" className="p-0 w-[260px]">
          <SheetTitle className="sr-only">Navigation</SheetTitle>
          <SheetDescription className="sr-only">Primary navigation drawer.</SheetDescription>
          <div className="flex h-16 items-center gap-3 border-b border-border px-lg">
            <span className="font-semibold tracking-tight text-text-primary">Lumen</span>
          </div>
          <Sidebar compact onNavigate={() => setLeftOpen(false)} className="border-r-0" />
        </SheetContent>
      </Sheet>

      {/* Search — clicking the bar opens a command-palette dialog */}
      <button
        type="button"
        onClick={() => setSearchOpen(true)}
        aria-label="Open search"
        className="relative hidden flex-1 items-center gap-2 rounded-md border border-border bg-surface-soft px-3 py-2 text-left text-body-small text-text-muted transition-colors hover:bg-surface-variant focus-ring md:flex md:max-w-xl"
      >
        <Search className="h-4 w-4 shrink-0 text-text-muted" />
        <span className="flex-1 truncate">Search transactions, stocks, goals…</span>
        <kbd className="hidden rounded border border-border bg-surface px-1.5 py-0.5 text-uppercase-label uppercase text-text-muted lg:inline-block">
          Ctrl K
        </kbd>
      </button>

      {/* Mobile: search trigger as an icon button */}
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className="md:hidden"
        aria-label="Open search"
        onClick={() => setSearchOpen(true)}
      >
        <Search className="h-5 w-5" />
      </Button>

      <div className="ml-auto flex items-center gap-1 md:gap-2">
        {/* Currency switcher — persists to user.base_currency via PATCH /me */}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              size="sm"
              className="gap-1.5 px-2 text-body-small font-medium"
              aria-label={`Base currency: ${currency}`}
              disabled={currencyMutation.isPending}
            >
              {currencyMutation.isPending ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <span className="tabular">{currency}</span>
              )}
              <ChevronDown className="h-3.5 w-3.5 text-text-muted" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="min-w-[140px]">
            {SUPPORTED_CURRENCIES.map((c) => (
              <DropdownMenuItem
                key={c}
                onSelect={() => {
                  if (c !== currency) currencyMutation.mutate(c as Currency);
                }}
                className="justify-between"
              >
                <span>{c}</span>
                {c === currency && (
                  <span className="text-uppercase-label text-primary">Active</span>
                )}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>

        {/* Notifications — popover with recent alerts + 'View all' link */}
        <AlertsPopover />

        {/* Mobile/tablet: open the right intelligence panel */}
        <Sheet open={rightOpen} onOpenChange={setRightOpen}>
          <SheetTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              className="xl:hidden"
              aria-label="Open intelligence panel"
            >
              <PanelRight className="h-5 w-5" />
            </Button>
          </SheetTrigger>
          <SheetContent side="right" className="w-[340px] p-0 sm:max-w-md">
            <SheetTitle className="sr-only">Intelligence panel</SheetTitle>
            <SheetDescription className="sr-only">Side panel with alerts, AI signals, and net worth snapshot.</SheetDescription>
            <IntelligencePanel className="border-l-0 w-full" />
          </SheetContent>
        </Sheet>
      </div>

      <SearchPalette open={searchOpen} onOpenChange={setSearchOpen} />
    </header>
  );
}
