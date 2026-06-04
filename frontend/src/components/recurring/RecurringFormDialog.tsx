import { useEffect } from "react";
import { useForm, Controller } from "react-hook-form";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { qk } from "@/lib/queryKeys";
import { SUPPORTED_CURRENCIES, type Currency } from "@/lib/constants";
import { useCurrency } from "@/hooks/useCurrency";
import { parseApiError } from "@/api/client";
import * as catApi from "@/api/categories.api";
import * as recApi from "@/api/recurring.api";
import { cn } from "@/lib/utils";

const RECURRING_FREQUENCIES: recApi.DetectedFrequency[] = [
  "weekly", "biweekly", "monthly", "yearly",
];

const FREQUENCY_LABELS: Record<recApi.DetectedFrequency, string> = {
  weekly: "Weekly (every 7 days)",
  biweekly: "Bi-weekly (every 14 days)",
  monthly: "Monthly",
  yearly: "Yearly",
};

const schema = z.object({
  name: z.string().min(1, "Required").max(120),
  merchant_pattern: z.string().min(1, "Required").max(200),
  amount: z.number().positive("Must be positive"),
  currency: z.enum(SUPPORTED_CURRENCIES),
  /** UI-level kind. Maps to backend `frequency` at submit: "once" stays as-is. */
  repeats: z.boolean(),
  frequency: z.enum(["weekly", "biweekly", "monthly", "yearly"]),
  start_date: z.string().min(1, "Required"),
  category_id: z.string().optional(),
  is_income: z.boolean(),
  auto_create_transaction: z.boolean(),
});
type Values = z.infer<typeof schema>;

interface PrefillSuggestion {
  name?: string;
  merchant_pattern?: string;
  amount?: number;
  currency?: Currency;
  frequency?: recApi.Frequency;
  is_income?: boolean;
}

interface Props {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  /** When provided: edit mode. When null + open: create mode. */
  editing?: recApi.RecurringPayment | null;
  /** Optional pre-fill from a detection suggestion. */
  prefill?: PrefillSuggestion;
}

export function RecurringFormDialog({ open, onOpenChange, editing, prefill }: Props) {
  const baseCurrency = useCurrency();
  const qc = useQueryClient();
  const isEditing = !!editing;

  const categoriesQuery = useQuery({
    queryKey: qk.categories.all(),
    queryFn: catApi.listCategories,
    enabled: open,
  });

  const todayIso = new Date().toISOString().slice(0, 10);
  const {
    register,
    handleSubmit,
    control,
    reset,
    watch,
    formState: { errors },
  } = useForm<Values>({
    defaultValues: {
      name: "",
      merchant_pattern: "",
      amount: 0,
      currency: baseCurrency,
      repeats: true,
      frequency: "monthly",
      start_date: todayIso,
      category_id: "",
      is_income: false,
      auto_create_transaction: false,
    },
  });

  const repeats = watch("repeats");
  const isIncome = watch("is_income");

  useEffect(() => {
    if (!open) return;
    if (editing) {
      reset({
        name: editing.name,
        merchant_pattern: editing.merchant_pattern,
        amount: editing.amount,
        currency: editing.currency,
        repeats: editing.frequency !== "once",
        frequency: editing.frequency === "once" ? "monthly" : editing.frequency,
        start_date: editing.start_date.slice(0, 10),
        category_id: editing.category_id ?? "",
        is_income: editing.is_income,
        auto_create_transaction: editing.auto_create_transaction,
      });
    } else {
      const prefillRepeats = prefill?.frequency ? prefill.frequency !== "once" : true;
      reset({
        name: prefill?.name ?? "",
        merchant_pattern: prefill?.merchant_pattern ?? "",
        amount: prefill?.amount ?? 0,
        currency: prefill?.currency ?? baseCurrency,
        repeats: prefillRepeats,
        frequency:
          prefill?.frequency && prefill.frequency !== "once"
            ? prefill.frequency
            : "monthly",
        start_date: todayIso,
        category_id: "",
        is_income: prefill?.is_income ?? false,
        // Sensible defaults: once-offs auto-log (user committed to them);
        // recurring stays off to avoid CSV-import duplicates.
        auto_create_transaction: !prefillRepeats,
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, editing, prefill, baseCurrency]);

  const mutation = useMutation({
    mutationFn: async (values: Values) => {
      // UTC midnight (not local noon) — see the matching note in
      // TransactionFormDialog. Avoids the false-future-date error when the
      // user opens the app before noon UTC.
      const isoStart = new Date(`${values.start_date}T00:00:00Z`).toISOString();
      const frequency: recApi.Frequency = values.repeats ? values.frequency : "once";
      const payload = {
        name: values.name.trim(),
        merchant_pattern: values.merchant_pattern.trim(),
        amount: values.amount,
        currency: values.currency as Currency,
        frequency,
        start_date: isoStart,
        category_id: values.category_id || undefined,
        is_income: values.is_income,
        auto_create_transaction: values.auto_create_transaction,
      };
      if (isEditing && editing) {
        return recApi.updateRecurring(editing.id, payload);
      }
      return recApi.createRecurring(payload);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.recurring.all() });
      onOpenChange(false);
    },
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{isEditing ? "Edit planned payment" : "Add a planned payment"}</DialogTitle>
          <DialogDescription>
            Track anything coming up — a recurring subscription, a friend's wedding, an annual tax
            bill. Planned payments show up on your calendar.
          </DialogDescription>
        </DialogHeader>

        <form
          id="rec-form"
          onSubmit={handleSubmit((v) => mutation.mutate(v))}
          className="space-y-md"
          noValidate
        >
          {mutation.isError && (
            <div
              role="alert"
              className="rounded-lg border border-danger/30 bg-danger/10 p-3 text-body-small text-danger"
            >
              {parseApiError(mutation.error)}
            </div>
          )}

          {/* Repeats? toggle. The whole rest of the form keys off this. */}
          <Controller
            name="repeats"
            control={control}
            render={({ field }) => (
              <div className="flex items-center justify-between rounded-lg border border-border bg-surface-soft p-3">
                <div className="min-w-0">
                  <div className="font-medium text-text-primary">Does this repeat?</div>
                  <div className="text-body-small text-text-muted">
                    {field.value
                      ? "Recurring — repeats automatically on its schedule."
                      : "One-off — a single planned payment."}
                  </div>
                </div>
                <div className="inline-flex shrink-0 rounded-lg border border-border bg-surface p-0.5">
                  <button
                    type="button"
                    onClick={() => field.onChange(true)}
                    className={cn(
                      "rounded-md px-3 py-1 text-body-small transition-colors",
                      field.value
                        ? "bg-primary text-on-primary font-semibold"
                        : "text-text-muted hover:bg-surface-soft",
                    )}
                  >
                    Repeats
                  </button>
                  <button
                    type="button"
                    onClick={() => field.onChange(false)}
                    className={cn(
                      "rounded-md px-3 py-1 text-body-small transition-colors",
                      !field.value
                        ? "bg-primary text-on-primary font-semibold"
                        : "text-text-muted hover:bg-surface-soft",
                    )}
                  >
                    One-off
                  </button>
                </div>
              </div>
            )}
          />

          <div className="space-y-1.5">
            <Label htmlFor="r-name">Display name</Label>
            <Input
              id="r-name"
              placeholder={repeats ? "Spotify Family" : "Andrei's wedding"}
              {...register("name")}
            />
            {errors.name && <p className="text-body-small text-danger">{errors.name.message}</p>}
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="r-pattern">Merchant pattern</Label>
            <Input
              id="r-pattern"
              placeholder={repeats ? "SPOTIFY*PREMIUM" : "Wedding gift — Andrei & Maria"}
              {...register("merchant_pattern")}
            />
            <p className="text-uppercase-label uppercase text-text-muted">
              We'll match transactions whose description contains this — case-insensitive.
            </p>
            {errors.merchant_pattern && (
              <p className="text-body-small text-danger">{errors.merchant_pattern.message}</p>
            )}
          </div>

          <div className="grid grid-cols-3 gap-2">
            <div className="col-span-2 space-y-1.5">
              <Label htmlFor="r-amount">Amount</Label>
              <Input
                id="r-amount"
                type="number"
                step="0.01"
                inputMode="decimal"
                className="tabular"
                {...register("amount", { valueAsNumber: true })}
              />
              {errors.amount && (
                <p className="text-body-small text-danger">{errors.amount.message}</p>
              )}
            </div>
            <div className="space-y-1.5">
              <Label>Currency</Label>
              <Controller
                name="currency"
                control={control}
                render={({ field }) => (
                  <select
                    {...field}
                    className="flex h-10 w-full rounded-lg border border-border bg-surface px-2 text-body focus-ring"
                  >
                    {SUPPORTED_CURRENCIES.map((c) => (
                      <option key={c}>{c}</option>
                    ))}
                  </select>
                )}
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2">
            {repeats ? (
              <div className="space-y-1.5">
                <Label htmlFor="r-freq">Frequency</Label>
                <Controller
                  name="frequency"
                  control={control}
                  render={({ field }) => (
                    <select
                      {...field}
                      id="r-freq"
                      className="flex h-10 w-full rounded-lg border border-border bg-surface px-3 text-body focus-ring"
                    >
                      {RECURRING_FREQUENCIES.map((f) => (
                        <option key={f} value={f}>
                          {FREQUENCY_LABELS[f]}
                        </option>
                      ))}
                    </select>
                  )}
                />
              </div>
            ) : (
              <div className="space-y-1.5">
                <Label>Cadence</Label>
                <div className="flex h-10 items-center rounded-lg border border-dashed border-border bg-surface-soft px-3 text-body-small text-text-muted">
                  One-off — no cadence
                </div>
              </div>
            )}
            <div className="space-y-1.5">
              <Label htmlFor="r-start">{repeats ? "Start date" : "Date due"}</Label>
              {/* On create we block past dates client-side so the server-side
                  "one-off in the past" refusal almost never fires. On edit we
                  leave it open — an existing recurring's start_date is a
                  cadence anchor that may legitimately be in the past, and
                  most edits don't touch the date. */}
              <Input
                id="r-start"
                type="date"
                min={isEditing ? undefined : todayIso}
                {...register("start_date")}
              />
              {errors.start_date && (
                <p className="text-body-small text-danger">{errors.start_date.message}</p>
              )}
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="r-cat">Category (optional)</Label>
            <Controller
              name="category_id"
              control={control}
              render={({ field }) => (
                <select
                  {...field}
                  id="r-cat"
                  className="flex h-10 w-full rounded-lg border border-border bg-surface px-3 text-body focus-ring"
                >
                  <option value="">— none —</option>
                  {(categoriesQuery.data ?? []).map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              )}
            />
          </div>

          <label className="flex items-center gap-2 rounded-lg border border-border bg-surface-soft p-3 text-body-small">
            <input
              type="checkbox"
              className="h-4 w-4 rounded border-border accent-primary focus-ring"
              {...register("is_income")}
            />
            <span className="font-medium text-text-primary">This is income</span>
            <span className="text-text-muted">— money coming in (e.g. salary)</span>
          </label>

          <label className="flex items-start gap-2 rounded-lg border border-border bg-surface-soft p-3 text-body-small">
            <input
              type="checkbox"
              className="mt-0.5 h-4 w-4 rounded border-border accent-primary focus-ring"
              {...register("auto_create_transaction")}
            />
            <span className="min-w-0">
              <span className="font-medium text-text-primary">
                Automatically log a transaction when due
              </span>
              <span className="block text-text-muted">
                {repeats
                  ? "Off by default."
                  : "Off by default."}
                {isIncome ? " Will be logged as income." : " Will be logged as an expense."}
              </span>
            </span>
          </label>
        </form>

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button form="rec-form" type="submit" variant="primary" disabled={mutation.isPending}>
            {mutation.isPending ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" /> Saving…
              </>
            ) : isEditing ? (
              "Save changes"
            ) : repeats ? (
              "Add recurring"
            ) : (
              "Add planned payment"
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
