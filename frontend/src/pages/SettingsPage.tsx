import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { KeyRound, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { SectionCard } from "@/components/shared/SectionCard";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useCurrency } from "@/hooks/useCurrency";
import { useAuthStore } from "@/store/authStore";
import * as meApi from "@/api/me.api";
import { parseApiError } from "@/api/client";
import { SUPPORTED_CURRENCIES, type Currency } from "@/lib/constants";

function initialsFor(name: string | undefined | null): string {
  if (!name) return "?";
  const parts = name.trim().split(/\s+/).slice(0, 2);
  return parts.map((p) => p[0]?.toUpperCase() ?? "").join("") || "?";
}

export default function SettingsPage() {
  return (
    <div className="space-y-lg animate-fade-in">
      <header>
        <h1 className="text-h2 font-h2 text-text-primary">Settings</h1>
        <p className="text-body-small text-text-muted">
          Manage your profile, base currency, and account security.
        </p>
      </header>

      <Tabs defaultValue="profile">
        <TabsList className="w-full sm:w-auto">
          <TabsTrigger value="profile">Profile</TabsTrigger>
          <TabsTrigger value="preferences">Preferences</TabsTrigger>
          <TabsTrigger value="security">Security</TabsTrigger>
        </TabsList>

        <TabsContent value="profile">
          <ProfilePanel />
        </TabsContent>

        <TabsContent value="preferences">
          <PreferencesPanel />
        </TabsContent>

        <TabsContent value="security">
          <SecurityPanel />
        </TabsContent>
      </Tabs>
    </div>
  );
}

function SecurityPanel() {
  const user = useAuthStore((s) => s.user);
  const clearAuth = useAuthStore((s) => s.clear);

  return (
    <>
      <SectionCard
        title="Password"
        description="Password changes are managed by the password-reset flow. We email you a one-time link to set a new password — even if you've forgotten the current one."
      >
        <div className="flex flex-wrap items-center justify-between gap-md rounded-lg border border-border bg-surface-soft p-md">
          <div>
            <div className="text-body-small font-medium text-text-primary">
              Send a password-reset link
            </div>
            <div className="text-uppercase-label uppercase text-text-muted">
              To {user?.email ?? "your account email"}
            </div>
          </div>
          <Button variant="primary" asChild>
            <Link to="/auth/forgot">
              <KeyRound className="h-4 w-4" /> Reset password
            </Link>
          </Button>
        </div>
      </SectionCard>

      <SectionCard
        title="Active session"
        description="Signing out clears this browser's access — your data stays safe on the server."
        className="mt-md"
      >
        <div className="flex items-center justify-between gap-md">
          <div>
            <div className="font-medium text-text-primary">This device</div>
            <div className="text-uppercase-label uppercase text-text-muted">
              Signed in as {user?.email ?? "—"}
            </div>
          </div>
          <Button
            variant="secondary"
            onClick={() => {
              clearAuth();
              window.location.href = "/auth";
            }}
          >
            Sign out
          </Button>
        </div>
      </SectionCard>
    </>
  );
}

function ProfilePanel() {
  const user = useAuthStore((s) => s.user);
  const setUser = useAuthStore((s) => s.setUser);
  const [fullName, setFullName] = useState(user?.full_name ?? "");
  const [okFlash, setOkFlash] = useState(false);

  // Resync if the auth store hands us a fresh user (e.g., after currency mutation).
  useEffect(() => {
    setFullName(user?.full_name ?? "");
  }, [user?.full_name]);

  const mutation = useMutation({
    mutationFn: (next: string) => meApi.updateMe({ full_name: next }),
    onSuccess: (u) => {
      setUser(u);
      setOkFlash(true);
      setTimeout(() => setOkFlash(false), 1800);
    },
  });

  const trimmed = fullName.trim();
  const dirty = trimmed.length > 0 && trimmed !== (user?.full_name ?? "");

  return (
    <SectionCard title="Profile">
      <div className="flex flex-col gap-md sm:flex-row sm:items-center">
        <div className="relative h-20 w-20 shrink-0">
          <div className="flex h-full w-full items-center justify-center rounded-full bg-primary text-h2 font-bold text-on-primary">
            {initialsFor(user?.full_name)}
          </div>
        </div>
        <div className="flex-1 space-y-md">
          <div className="space-y-1.5">
            <Label htmlFor="full-name">Full name</Label>
            <Input
              id="full-name"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              maxLength={120}
              disabled={mutation.isPending}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="email">Email</Label>
            <Input id="email" value={user?.email ?? ""} readOnly />
            <p className="text-uppercase-label uppercase text-text-muted">
              Email is your account identifier and cannot be changed yet.
            </p>
          </div>
        </div>
      </div>
      {mutation.isError && (
        <p className="mt-3 text-body-small text-danger">{parseApiError(mutation.error)}</p>
      )}
      {okFlash && (
        <p className="mt-3 text-body-small text-success">Profile saved.</p>
      )}
      <div className="mt-md flex justify-end">
        <Button
          variant="primary"
          disabled={!dirty || mutation.isPending}
          onClick={() => mutation.mutate(trimmed)}
        >
          {mutation.isPending ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" /> Saving…
            </>
          ) : (
            "Save changes"
          )}
        </Button>
      </div>
    </SectionCard>
  );
}

function PreferencesPanel() {
  const currency = useCurrency();
  const setUser = useAuthStore((s) => s.setUser);
  const qc = useQueryClient();

  const currencyMutation = useMutation({
    mutationFn: (next: Currency) => meApi.updateMe({ base_currency: next }),
    onSuccess: (user) => {
      setUser(user);
      // Backend just rewrote amount_base on every transaction (historical
      // rates) + monthly_budget on every category (today's rate) + the Net
      // cash flow account's currency stamp. Every cached money query is
      // stale. Invalidate everything.
      qc.invalidateQueries();
    },
  });

  return (
    <SectionCard title="Preferences">
      <div className="flex flex-col items-start justify-between gap-2 sm:flex-row sm:items-center">
        <div>
          <div className="font-medium text-text-primary">Base currency</div>
          <div className="text-body-small text-text-muted">
            Used as the display currency across the app. Transactions in other
            currencies are converted using exchange rates from their original date.
          </div>
        </div>
        <select
          value={currency}
          disabled={currencyMutation.isPending}
          onChange={(e) => currencyMutation.mutate(e.target.value as Currency)}
          className="flex h-10 w-32 rounded-lg border border-border bg-surface px-3 text-body focus-ring disabled:opacity-50"
        >
          {SUPPORTED_CURRENCIES.map((c) => (
            <option key={c}>{c}</option>
          ))}
        </select>
      </div>
      {currencyMutation.isError && (
        <p className="mt-3 text-body-small text-danger">
          {parseApiError(currencyMutation.error)}
        </p>
      )}
    </SectionCard>
  );
}
