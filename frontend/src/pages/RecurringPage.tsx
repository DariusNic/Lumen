import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Calendar as CalendarIcon,
  CalendarClock,
  ExternalLink,
  Loader2,
  MoreHorizontal,
  Plus,
  Repeat,
  Sparkles,
  Target,
  Trash2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { SectionCard } from "@/components/shared/SectionCard";
import { EmptyState } from "@/components/shared/EmptyState";
import { MonthPicker, type YearMonth } from "@/components/shared/MonthPicker";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { RecurringFormDialog } from "@/components/recurring/RecurringFormDialog";
import { DetectSuggestionsDialog } from "@/components/recurring/DetectSuggestionsDialog";
import { qk } from "@/lib/queryKeys";
import { formatMoney } from "@/lib/format";
import { parseApiError } from "@/api/client";
import { useCurrency } from "@/hooks/useCurrency";
import type { Currency } from "@/lib/constants";
import * as recApi from "@/api/recurring.api";
import { cn } from "@/lib/utils";

const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

const FREQ_LABEL: Record<recApi.Frequency, string> = {
  once: "One-off",
  weekly: "Weekly",
  biweekly: "Bi-weekly",
  monthly: "Monthly",
  yearly: "Yearly",
};

export default function PlannedPage() {
  const qc = useQueryClient();
  const currency = useCurrency();
  const [calMonth, setCalMonth] = useState<YearMonth>(MonthPicker.thisMonth());
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<recApi.RecurringPayment | null>(null);
  const [prefill, setPrefill] = useState<{
    name?: string;
    merchant_pattern?: string;
    amount?: number;
    currency?: "RON" | "EUR" | "USD";
    frequency?: recApi.Frequency;
    is_income?: boolean;
  } | undefined>(undefined);
  const [detectionResult, setDetectionResult] = useState<recApi.DetectionResult | null>(null);
  const [detectOpen, setDetectOpen] = useState(false);
  const [deleteCandidate, setDeleteCandidate] = useState<recApi.RecurringPayment | null>(null);
  // Goal-contribution visibility filter. "all" = default; "hide" suppresses
  // them from the lists (Income is unaffected — goal contributions are
  // always expenses); "only" shows just them. The calendar uses the same
  // filter so a "hide" view doesn't surface them in the day pop-out either.
  const [goalFilter, setGoalFilter] = useState<"all" | "hide" | "only">("all");
  // Clicking a calendar cell with more than two events expands a dialog
  // showing the full list for that day. `null` means no day is expanded.
  const [expandedDay, setExpandedDay] = useState<{
    date: Date;
    events: recApi.RecurringPayment[];
  } | null>(null);

  const listQuery = useQuery({
    queryKey: qk.recurring.all(),
    queryFn: recApi.listRecurring,
  });
  const calQuery = useQuery({
    queryKey: qk.recurring.calendar(calMonth.year, calMonth.month),
    queryFn: () => recApi.getCalendar(calMonth.year, calMonth.month),
  });

  const detectMutation = useMutation({
    mutationFn: () => recApi.detectRecurring(),
    onSuccess: (data) => {
      setDetectionResult(data);
      setDetectOpen(true);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => recApi.deleteRecurring(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.recurring.all() });
      setDeleteCandidate(null);
    },
  });

  /** "Pay" button on overdue / due-today non-auto rows. Creates the
   *  transaction and rolls next_due forward by one cadence step, which
   *  removes the "Xd overdue" badge on the next list render. */
  const markPaidMutation = useMutation({
    mutationFn: (id: string) => recApi.markPaid(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.recurring.all() });
      qc.invalidateQueries({ queryKey: qk.transactions.all() });
      qc.invalidateQueries({ queryKey: qk.networth.all() });
    },
  });

  const allItems = listQuery.data ?? [];
  // Apply the goal-contribution filter at the source so it ripples to the
  // list AND the "total outgoing" header math AND the calendar pop-out.
  const items = allItems.filter((r) => {
    if (goalFilter === "hide") return r.goal_id === null;
    if (goalFilter === "only") return r.goal_id !== null;
    return true;
  });
  const goalContribCount = allItems.filter((r) => r.goal_id !== null).length;
  const income = items.filter((r) => r.is_income);
  const expenses = items.filter((r) => !r.is_income);
  // `amount_base` comes pre-converted from the backend so the total is
  // currency-correct even when items mix RON/EUR/USD. Falls back to `amount`
  // (face-value) if FX was unavailable on the backend.
  const baseCurrency = currency;

  // "This month" total: amount actually expected to be paid in the displayed
  // calendar month — once-offs counted only if next_due falls in the month,
  // recurring counted by occurrence count (not normalized ÷4.33 fakery).
  const thisMonthOutflow = expenses.reduce(
    (s, r) => s + occurrencesInMonth(r, calMonth) * (r.amount_base ?? r.amount),
    0,
  );

  if (listQuery.isLoading) {
    return (
      <div className="flex items-center justify-center gap-2 py-2xl text-body-small text-text-muted">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading planned payments…
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <>
        <EmptyState
          icon={CalendarClock}
          title="No planned payments yet"
          description="Add recurring outflows (rent, subscriptions, salary) and one-off plans (a wedding, a tax bill, a planned trip). They show up on the calendar."
          action={
            <div className="flex flex-wrap gap-2">
              <Button
                variant="secondary"
                onClick={() => detectMutation.mutate()}
                disabled={detectMutation.isPending}
              >
                {detectMutation.isPending ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" /> Scanning…
                  </>
                ) : (
                  <>
                    <Sparkles className="h-4 w-4" /> Detect from transactions
                  </>
                )}
              </Button>
              <Button
                variant="primary"
                onClick={() => {
                  setEditing(null);
                  setPrefill(undefined);
                  setFormOpen(true);
                }}
              >
                <Plus className="h-4 w-4" /> Add manually
              </Button>
            </div>
          }
        />
        <RecurringFormDialog
          open={formOpen}
          onOpenChange={(o) => {
            setFormOpen(o);
            if (!o) {
              setEditing(null);
              setPrefill(undefined);
            }
          }}
          editing={editing}
          prefill={prefill}
        />
        <DetectSuggestionsDialog
          open={detectOpen}
          onOpenChange={setDetectOpen}
          result={detectionResult}
          onConfirm={(s) => {
            setPrefill({
              name: s.merchant_pattern,
              merchant_pattern: s.merchant_pattern,
              amount: s.average_amount,
              currency: s.currency,
              frequency: s.frequency,
              is_income: s.is_income,
            });
            setEditing(null);
            setDetectOpen(false);
            setFormOpen(true);
          }}
        />
      </>
    );
  }

  const monthLabel = `${MONTH_NAMES[calMonth.month - 1]} ${calMonth.year}`;

  return (
    <div className="space-y-lg animate-fade-in">
      <header className="flex flex-wrap items-center justify-between gap-md">
        <div>
          <h1 className="text-h2 font-h2 text-text-primary">Planned payments</h1>
          <p className="text-body-small text-text-muted">
            {expenses.length} expense{expenses.length === 1 ? "" : "s"} ·{" "}
            {income.length} income source{income.length === 1 ? "" : "s"} · Total:{" "}
            <span className="font-semibold text-text-primary tabular">
              {formatMoney(thisMonthOutflow, baseCurrency)}
            </span>{" "}
            outgoing in {monthLabel}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="secondary"
            onClick={() => detectMutation.mutate()}
            disabled={detectMutation.isPending}
          >
            {detectMutation.isPending ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" /> Scanning…
              </>
            ) : (
              <>
                <Sparkles className="h-4 w-4" /> Detect
              </>
            )}
          </Button>
          <Button
            variant="primary"
            onClick={() => {
              setEditing(null);
              setPrefill(undefined);
              setFormOpen(true);
            }}
          >
            <Plus className="h-4 w-4" /> Add planned payment
          </Button>
        </div>
      </header>

      {detectMutation.isError && (
        <div role="alert" className="rounded-lg border border-danger/30 bg-danger/10 p-3 text-body-small text-danger">
          {parseApiError(detectMutation.error)}
        </div>
      )}

      {goalContribCount > 0 && (
        <div className="flex flex-wrap items-center gap-2 text-body-small text-text-muted">
          <Target className="h-4 w-4 text-primary" />
          <span>
            {goalContribCount} goal contribution{goalContribCount === 1 ? "" : "s"} —
            managed from the Goals page.
          </span>
          <div className="ml-auto inline-flex rounded-md border border-border bg-surface p-0.5">
            {(["all", "hide", "only"] as const).map((mode) => (
              <button
                key={mode}
                type="button"
                onClick={() => setGoalFilter(mode)}
                className={cn(
                  "rounded px-2 py-1 text-uppercase-label uppercase transition-colors",
                  goalFilter === mode
                    ? "bg-primary text-on-primary"
                    : "text-text-muted hover:text-text-primary",
                )}
              >
                {mode === "all" ? "Show all" : mode === "hide" ? "Hide goals" : "Goals only"}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="grid gap-md lg:grid-cols-5">
        {/* List */}
        <SectionCard noPadding className="lg:col-span-3">
          {income.length > 0 && (
            <>
              <div className="border-b border-border bg-surface-soft px-md py-2 text-uppercase-label uppercase text-success">
                Income
              </div>
              <ul className="divide-y divide-border">
                {income.map((r) => (
                  <RecurringRow
                    key={r.id}
                    r={r}
                    onEdit={() => {
                      setEditing(r);
                      setPrefill(undefined);
                      setFormOpen(true);
                    }}
                    onDelete={() => setDeleteCandidate(r)}
                  />
                ))}
              </ul>
            </>
          )}
          <div className="border-y border-border bg-surface-soft px-md py-2 text-uppercase-label uppercase text-text-muted">
            Expenses · sorted by next due
          </div>
          <ul className="divide-y divide-border">
            {expenses.map((r) => (
              <RecurringRow
                key={r.id}
                r={r}
                onEdit={() => {
                  setEditing(r);
                  setPrefill(undefined);
                  setFormOpen(true);
                }}
                onDelete={() => setDeleteCandidate(r)}
                onPay={() => markPaidMutation.mutate(r.id)}
                payPending={markPaidMutation.isPending && markPaidMutation.variables === r.id}
              />
            ))}
            {expenses.length === 0 && (
              <li className="px-md py-md text-body-small text-text-muted">
                No expenses planned yet.
              </li>
            )}
          </ul>
        </SectionCard>

        {/* Calendar — the MonthPicker is self-explanatory; no title needed
            in such a narrow column (323 px at 1440 with the IP panel open).
            Unlike the Budget / Reports pages this picker also allows
            future months — the whole point of Planned is to look ahead
            at what's coming. Cap at 5 years out so the picker doesn't
            invite typos into the year 3000. */}
        <SectionCard className="lg:col-span-2">
          <div className="mb-md flex justify-end">
            <MonthPicker
              value={calMonth}
              onChange={setCalMonth}
              min={(() => {
                const t = MonthPicker.thisMonth();
                return { year: t.year - 5, month: t.month };
              })()}
              max={(() => {
                const t = MonthPicker.thisMonth();
                return { year: t.year + 5, month: t.month };
              })()}
            />
          </div>
          <CalendarGrid
            month={calMonth}
            byDay={filterByDay(calQuery.data?.by_day ?? {}, goalFilter)}
            onDayClick={(day, events) => {
              setExpandedDay({
                date: new Date(calMonth.year, calMonth.month - 1, day),
                events,
              });
            }}
          />
        </SectionCard>
      </div>

      <RecurringFormDialog
        open={formOpen}
        onOpenChange={(o) => {
          setFormOpen(o);
          if (!o) {
            setEditing(null);
            setPrefill(undefined);
          }
        }}
        editing={editing}
        prefill={prefill}
      />

      <DetectSuggestionsDialog
        open={detectOpen}
        onOpenChange={setDetectOpen}
        result={detectionResult}
        onConfirm={(s) => {
          setPrefill({
            name: s.merchant_pattern,
            merchant_pattern: s.merchant_pattern,
            amount: s.average_amount,
            currency: s.currency,
            frequency: s.frequency,
            is_income: s.is_income,
          });
          setEditing(null);
          setDetectOpen(false);
          setFormOpen(true);
        }}
      />

      <ConfirmDelete
        candidate={deleteCandidate}
        onClose={() => setDeleteCandidate(null)}
        onConfirm={(id) => deleteMutation.mutate(id)}
        isPending={deleteMutation.isPending}
      />

      <DayDetailDialog
        day={expandedDay}
        onClose={() => setExpandedDay(null)}
        baseCurrency={baseCurrency}
        payPending={markPaidMutation.isPending}
        onAction={(id) => markPaidMutation.mutate(id)}
      />
    </div>
  );
}

/** Apply the goal-contribution filter to the calendar's by-day map so the
 *  visual grid AND the day pop-out stay consistent with the list above. */
function filterByDay(
  byDay: Record<string, recApi.RecurringPayment[]>,
  mode: "all" | "hide" | "only",
): Record<string, recApi.RecurringPayment[]> {
  if (mode === "all") return byDay;
  const out: Record<string, recApi.RecurringPayment[]> = {};
  for (const [day, events] of Object.entries(byDay)) {
    const filtered = events.filter((e) =>
      mode === "hide" ? e.goal_id === null : e.goal_id !== null,
    );
    if (filtered.length > 0) out[day] = filtered;
  }
  return out;
}

/** How many times this payment fires inside the displayed calendar month.
 *  Drives the "Total outgoing in <month>" header. */
function occurrencesInMonth(r: recApi.RecurringPayment, m: YearMonth): number {
  const firstDay = new Date(m.year, m.month - 1, 1);
  const lastDay = new Date(m.year, m.month, 0); // day 0 of next month = last of this
  const startMs = firstDay.getTime();
  const endMs = lastDay.getTime() + 24 * 60 * 60 * 1000 - 1;
  const nextDue = new Date(r.next_due).getTime();

  if (r.frequency === "once") {
    return nextDue >= startMs && nextDue <= endMs ? 1 : 0;
  }

  // For recurring, walk forward in cadence steps from next_due, counting any
  // occurrence that falls within the month window.
  const stepDays =
    r.frequency === "weekly" ? 7 :
    r.frequency === "biweekly" ? 14 :
    r.frequency === "yearly" ? 365 :
    30; // monthly approximation
  const stepMs = stepDays * 24 * 60 * 60 * 1000;

  let count = 0;
  let cursor = nextDue;
  // Walk backwards if next_due is past the month end (shouldn't happen for active rows)
  while (cursor > endMs && cursor - stepMs >= startMs) {
    cursor -= stepMs;
  }
  while (cursor <= endMs) {
    if (cursor >= startMs) count += 1;
    cursor += stepMs;
  }
  return count;
}

/** Days from today to `iso`. Negative = overdue. */
function daysUntil(iso: string): number {
  const due = new Date(iso);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  due.setHours(0, 0, 0, 0);
  return Math.round((due.getTime() - today.getTime()) / (24 * 60 * 60 * 1000));
}

function relativeNextDue(iso: string): string {
  const diff = daysUntil(iso);
  if (diff === 0) return "today";
  if (diff === 1) return "tomorrow";
  if (diff === -1) return "yesterday";
  if (diff > 0 && diff <= 14) return `in ${diff} days`;
  if (diff < 0 && diff >= -14) return `${Math.abs(diff)} days ago`;
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function RecurringRow({
  r,
  onEdit,
  onDelete,
  onPay,
  payPending,
}: {
  r: recApi.RecurringPayment;
  onEdit: () => void;
  onDelete: () => void;
  onPay?: () => void;
  payPending?: boolean;
}) {
  const navigate = useNavigate();
  const baseCurrency = useCurrency();
  // Goal-linked recurrings are owned by their goal — amount, cadence and
  // start_date all live in the Goals page's auto-contribute UI. Editing /
  // deleting them from Planned would either no-op (the goal flow re-creates
  // the recurring on its next edit) or orphan the goal's auto state. Block
  // both actions at the menu level and surface a link to Goals instead.
  const isGoalLinked = r.goal_id !== null;
  const isOnce = r.frequency === "once";
  const days = daysUntil(r.next_due);
  // Display amount in the user's base currency to match the Goals/Dashboard
  // convention; show the native amount as a small subline when the row's
  // currency differs from the user's base. Falls back to native-only when
  // `amount_base` is null (FX unavailable on the most recent fetch).
  const showNativeSubline = r.currency !== baseCurrency && r.amount_base != null;
  const primaryAmount = r.amount_base != null && r.amount_base !== r.amount
    ? Math.abs(r.amount_base)
    : r.amount;
  const primaryCurrency = r.amount_base != null && r.currency !== baseCurrency
    ? baseCurrency
    : r.currency;
  const signPrefix = r.is_income ? "+" : "−";
  // Action button only renders on rows where the user has to record the
  // transaction manually — non-auto rows. Auto rows are handled by the
  // cron. The button is visible always but disabled when not due yet, so
  // the user sees "yes this can be acted on, but you don't need to" rather
  // than the button vanishing after a pay/receive.
  // Label switches per direction: expenses → "Pay", income → "Receive".
  // The backend `mark_paid` endpoint already mirrors the sign correctly
  // (positive tx for income, negative for expense), so one button + one
  // mutation covers both.
  const showActionButton = !r.auto_create_transaction;
  const isDue = days <= 0;
  return (
    <li className="flex flex-col gap-2 px-md py-3 transition-colors hover:bg-surface-soft sm:flex-row sm:items-center sm:gap-md">
      <div className="flex min-w-0 items-center gap-md sm:flex-1">
        <span
          className={cn(
            "flex h-9 w-9 shrink-0 items-center justify-center rounded-full",
            r.is_income ? "bg-success/15 text-success" : "bg-primary-tint text-primary",
          )}
        >
          {isOnce ? <CalendarClock className="h-4 w-4" /> : <Repeat className="h-4 w-4" />}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="font-medium text-text-primary truncate">{r.name}</span>
            {r.auto_create_transaction && (
              <span
                className="rounded-full bg-primary-tint px-1.5 py-0.5 text-[10px] uppercase text-primary"
                title="A transaction is auto-logged when this is due"
              >
                auto
              </span>
            )}
          </div>
          {/* Goal-linked recurrings carry an internal `GOAL:<oid>` pattern
              for the join — show a friendly label instead so the user
              never sees the raw id. */}
          <div className="text-uppercase-label uppercase text-text-muted truncate">
            {r.goal_id ? "Goal contribution" : r.merchant_pattern}
          </div>
        </div>
      </div>
      <div className="flex items-center justify-between gap-2 sm:gap-md">
        <span
          className={cn(
            "rounded-full border px-2 py-0.5 text-uppercase-label uppercase",
            isOnce
              ? "border-warning/40 bg-warning/10 text-warning-700"
              : "border-border text-text-muted",
          )}
        >
          {FREQ_LABEL[r.frequency]}
        </span>
        <div className="text-right shrink-0">
          <div
            className={cn(
              "font-semibold tabular",
              r.is_income ? "text-success" : "text-text-primary",
            )}
          >
            {signPrefix}
            {formatMoney(primaryAmount, primaryCurrency)}
          </div>
          {showNativeSubline && (
            <div className="text-uppercase-label uppercase text-text-muted tabular">
              {signPrefix}{formatMoney(r.amount, r.currency)}
            </div>
          )}
          {(() => {
            const overdue = days < 0;
            // "Overdue" implies the user owes the money, so it fits expenses
            // but reads wrong on income (you don't *owe* income — you just
            // haven't received it yet). Swap the label per direction; keep
            // the danger color either way, since money missing from an
            // expected inflow is still worth flagging.
            const lateLabel = r.is_income
              ? `${Math.abs(days)}d late`
              : `${Math.abs(days)}d overdue`;
            const label = overdue
              ? lateLabel
              : `${isOnce ? "Due " : "Next "}${relativeNextDue(r.next_due)}`;
            return (
              <div
                className={cn(
                  "text-uppercase-label uppercase",
                  overdue ? "text-danger" : "text-text-muted",
                )}
              >
                {label}
              </div>
            );
          })()}
        </div>
        {showActionButton && (
          <Button
            variant="primary"
            size="sm"
            onClick={onPay}
            disabled={payPending || !isDue}
            title={
              !isDue
                ? r.is_income
                  ? "Already received for this cycle"
                  : "Already paid for this cycle"
                : undefined
            }
            className="shrink-0"
          >
            {payPending ? "…" : r.is_income ? "Receive" : "Pay"}
          </Button>
        )}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon-sm" aria-label="Planned payment options">
              <MoreHorizontal className="h-4 w-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            {isGoalLinked ? (
              <DropdownMenuItem onSelect={() => navigate("/goals")}>
                <ExternalLink className="h-3.5 w-3.5" /> Manage in Goals
              </DropdownMenuItem>
            ) : (
              <>
                <DropdownMenuItem onSelect={onEdit}>Edit</DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  onSelect={onDelete}
                  className="text-danger focus:bg-danger/10 focus:text-danger"
                >
                  <Trash2 className="h-3.5 w-3.5" /> Delete
                </DropdownMenuItem>
              </>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </li>
  );
}

function CalendarGrid({
  month,
  byDay,
  onDayClick,
}: {
  month: YearMonth;
  byDay: Record<string, recApi.RecurringPayment[]>;
  onDayClick: (day: number, events: recApi.RecurringPayment[]) => void;
}) {
  // First day of month → weekday (0 = Sun, shift to Mon-first)
  const first = new Date(month.year, month.month - 1, 1);
  const dayOfWeek = (first.getDay() + 6) % 7; // Mon = 0
  const daysInMonth = new Date(month.year, month.month, 0).getDate();

  const today = new Date();
  const isThisMonth = today.getFullYear() === month.year && today.getMonth() + 1 === month.month;

  return (
    <div>
      <div className="mb-1 grid grid-cols-7 gap-1 text-center text-uppercase-label uppercase text-text-muted">
        {["M", "T", "W", "T", "F", "S", "S"].map((d, i) => (
          <div key={i}>{d}</div>
        ))}
      </div>
      <div className="grid grid-cols-7 gap-1">
        {Array.from({ length: 35 }, (_, i) => {
          const day = i - dayOfWeek + 1;
          const inMonth = day >= 1 && day <= daysInMonth;
          const events = inMonth ? byDay[String(day)] ?? [] : [];
          const isToday = isThisMonth && day === today.getDate();
          const clickable = inMonth && events.length > 0;
          const CellTag: "button" | "div" = clickable ? "button" : "div";
          return (
            <CellTag
              key={i}
              type={clickable ? "button" : undefined}
              onClick={clickable ? () => onDayClick(day, events) : undefined}
              aria-label={
                clickable
                  ? `Show ${events.length} planned payment${events.length === 1 ? "" : "s"} on day ${day}`
                  : undefined
              }
              className={cn(
                "relative flex min-h-[68px] flex-col items-start gap-0.5 rounded-md p-1 text-left transition-colors",
                inMonth ? "hover:bg-surface-soft" : "opacity-30",
                clickable && "cursor-pointer focus-ring",
              )}
            >
              <span
                className={cn(
                  "text-body-small tabular",
                  isToday
                    ? "flex h-6 w-6 items-center justify-center rounded-full bg-primary text-on-primary font-semibold"
                    : "text-text-primary",
                )}
              >
                {inMonth ? day : ""}
              </span>
              <div className="flex w-full flex-col gap-0.5">
                {events.slice(0, 2).map((e) => (
                  <span
                    key={e.id}
                    title={`${e.name} — ${formatMoney(e.amount, e.currency)}${e.frequency === "once" ? " (one-off)" : ""}`}
                    className={cn(
                      "block truncate rounded px-1 text-[9px]",
                      e.is_income
                        ? "bg-success/15 text-success"
                        : e.frequency === "once"
                          ? "bg-warning/15 text-warning-700"
                          : "bg-primary-tint text-primary",
                    )}
                  >
                    {e.name.split(" ")[0]}
                  </span>
                ))}
                {events.length > 2 && (
                  <span className="text-[9px] font-medium text-primary">
                    +{events.length - 2} more
                  </span>
                )}
              </div>
            </CellTag>
          );
        })}
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-3 border-t border-border pt-3 text-uppercase-label uppercase text-text-muted">
        <span className="inline-flex items-center gap-1">
          <span className="h-2 w-2 rounded-full bg-primary" /> Recurring
        </span>
        <span className="inline-flex items-center gap-1">
          <span className="h-2 w-2 rounded-full bg-warning-700" /> One-off
        </span>
        <span className="inline-flex items-center gap-1">
          <span className="h-2 w-2 rounded-full bg-success" /> Income
        </span>
        <span className="ml-auto inline-flex items-center gap-1">
          <CalendarIcon className="h-3 w-3" /> only the next occurrence is shown
        </span>
      </div>
    </div>
  );
}

function ConfirmDelete({
  candidate,
  onClose,
  onConfirm,
  isPending,
}: {
  candidate: recApi.RecurringPayment | null;
  onClose: () => void;
  onConfirm: (id: string) => void;
  isPending: boolean;
}) {
  return (
    <Dialog open={!!candidate} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Delete this planned payment?</DialogTitle>
          <DialogDescription>
            The schedule will stop tracking new occurrences. Past transactions tagged to it stay
            unchanged in your history.
          </DialogDescription>
        </DialogHeader>
        {candidate && (
          <div className="rounded-lg border border-border bg-surface-soft p-3 text-body-small">
            <div className="font-medium text-text-primary">{candidate.name}</div>
            <div className="text-text-muted tabular">
              {FREQ_LABEL[candidate.frequency]} ·{" "}
              {formatMoney(candidate.amount, candidate.currency)}
            </div>
          </div>
        )}
        <DialogFooter>
          <Button variant="ghost" onClick={onClose} disabled={isPending}>
            Cancel
          </Button>
          <Button
            variant="danger"
            onClick={() => candidate && onConfirm(candidate.id)}
            disabled={isPending}
          >
            {isPending ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" /> Deleting…
              </>
            ) : (
              <>
                <Trash2 className="h-4 w-4" /> Delete
              </>
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}


/** Modal triggered by clicking a calendar day. Lists every planned payment
 *  whose `next_due` falls on that day, with Pay / Receive buttons for the
 *  non-auto rows that are actually due now (or overdue). Auto rows render
 *  read-only since the cron handles them.
 */
function DayDetailDialog({
  day,
  onClose,
  baseCurrency,
  payPending,
  onAction,
}: {
  day: { date: Date; events: recApi.RecurringPayment[] } | null;
  onClose: () => void;
  baseCurrency: Currency;
  payPending: boolean;
  onAction: (id: string) => void;
}) {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const dayIsToday = day && day.date.toDateString() === today.toDateString();
  // "Due now" = the displayed day is at or before today. Past-or-present
  // gates the action button — future-dated planned payments can't be paid
  // ahead of time from this dialog.
  const dayIsDue = !!day && day.date.getTime() <= today.getTime();
  return (
    <Dialog open={!!day} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>
            {day
              ? day.date.toLocaleDateString(undefined, {
                  weekday: "long",
                  month: "long",
                  day: "numeric",
                })
              : ""}
          </DialogTitle>
          <DialogDescription>
            {day && day.events.length === 1
              ? "1 planned payment on this day."
              : day
                ? `${day.events.length} planned payments on this day.`
                : ""}
            {dayIsToday && " You can mark them as completed from here."}
          </DialogDescription>
        </DialogHeader>

        {day && (
          <ul className="divide-y divide-border rounded-lg border border-border">
            {day.events.map((e) => {
              const isOnce = e.frequency === "once";
              const signPrefix = e.is_income ? "+" : "−";
              const showActionButton = !e.auto_create_transaction;
              const showNativeSubline =
                e.currency !== baseCurrency && e.amount_base != null;
              const primaryAmount =
                e.amount_base != null && e.amount_base !== e.amount
                  ? Math.abs(e.amount_base)
                  : e.amount;
              const primaryCurrency =
                e.amount_base != null && e.currency !== baseCurrency
                  ? baseCurrency
                  : e.currency;
              return (
                <li key={e.id} className="flex items-center gap-md p-3 text-body-small">
                  <span
                    className={cn(
                      "flex h-8 w-8 shrink-0 items-center justify-center rounded-full",
                      e.is_income
                        ? "bg-success/15 text-success"
                        : "bg-primary-tint text-primary",
                    )}
                  >
                    {isOnce ? (
                      <CalendarClock className="h-4 w-4" />
                    ) : (
                      <Repeat className="h-4 w-4" />
                    )}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="truncate font-medium text-text-primary">{e.name}</div>
                    <div className="text-uppercase-label uppercase text-text-muted">
                      {FREQ_LABEL[e.frequency]}
                      {e.auto_create_transaction && " · auto"}
                    </div>
                  </div>
                  <div className="text-right">
                    <div
                      className={cn(
                        "font-semibold tabular",
                        e.is_income ? "text-success" : "text-text-primary",
                      )}
                    >
                      {signPrefix}
                      {formatMoney(primaryAmount, primaryCurrency)}
                    </div>
                    {showNativeSubline && (
                      <div className="text-uppercase-label uppercase text-text-muted tabular">
                        {signPrefix}
                        {formatMoney(e.amount, e.currency)}
                      </div>
                    )}
                  </div>
                  {showActionButton && (
                    <Button
                      variant="primary"
                      size="sm"
                      onClick={() => onAction(e.id)}
                      disabled={payPending || !dayIsDue}
                      title={!dayIsDue ? "Not due yet" : undefined}
                    >
                      {payPending ? "…" : e.is_income ? "Receive" : "Pay"}
                    </Button>
                  )}
                </li>
              );
            })}
          </ul>
        )}

        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
