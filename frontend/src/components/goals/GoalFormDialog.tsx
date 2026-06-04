import { useEffect } from "react";
import { useForm, Controller } from "react-hook-form";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";
import { Flag, GraduationCap, Home, Loader2, Plane, ShieldCheck, Sparkles } from "lucide-react";
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
import * as goalsApi from "@/api/goals.api";
import { cn } from "@/lib/utils";

const TYPE_OPTIONS: { id: goalsApi.GoalType; label: string; icon: typeof Plane }[] = [
  { id: "travel", label: "Travel", icon: Plane },
  { id: "home", label: "Home", icon: Home },
  { id: "emergency", label: "Emergency", icon: ShieldCheck },
  { id: "education", label: "Education", icon: GraduationCap },
  { id: "vehicle", label: "Vehicle", icon: Sparkles },
  { id: "other", label: "Other", icon: Flag },
];

const schema = z
  .object({
    name: z.string().min(1, "Required").max(80),
    target_amount: z.number().positive("Must be positive"),
    currency: z.enum(SUPPORTED_CURRENCIES),
    target_date: z
      .string()
      .min(1, "Required")
      .refine(
        (s) => new Date(`${s}T23:59:59`).getTime() > Date.now(),
        { message: "Target date must be in the future" },
      ),
    type: z.enum(["travel", "home", "emergency", "education", "vehicle", "other"]),
    priority: z.number().int().min(1).max(5),
    initial_deposit: z.number().nonnegative().optional(),
    auto_contribute_enabled: z.boolean(),
    auto_contribute_amount: z.number().nonnegative().optional(),
    auto_contribute_start_date: z.string().optional(),
  })
  .refine((d) => (d.initial_deposit ?? 0) <= d.target_amount, {
    message: "Initial deposit can't exceed target",
    path: ["initial_deposit"],
  })
  .refine(
    (d) => !d.auto_contribute_enabled || (d.auto_contribute_amount ?? 0) > 0,
    {
      message: "Monthly amount is required when auto-contribute is on",
      path: ["auto_contribute_amount"],
    },
  )
  .refine(
    (d) =>
      !d.auto_contribute_enabled ||
      (!!d.auto_contribute_start_date && d.auto_contribute_start_date.length >= 8),
    {
      message: "Pick a starting date",
      path: ["auto_contribute_start_date"],
    },
  );
type Values = z.infer<typeof schema>;

/** First-of-next-month, YYYY-MM-DD — the sensible default for "start
 *  contributing soon" UX. */
function firstOfNextMonth(): string {
  const d = new Date();
  d.setMonth(d.getMonth() + 1, 1);
  return d.toISOString().slice(0, 10);
}

interface Props {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  /** When provided, dialog opens in edit mode and pre-fills from this goal. */
  editing?: goalsApi.Goal | null;
}

export function GoalFormDialog({ open, onOpenChange, editing }: Props) {
  const baseCurrency = useCurrency();
  const qc = useQueryClient();
  const isEditing = !!editing;

  const {
    register,
    handleSubmit,
    control,
    reset,
    watch,
    setValue,
    formState: { errors },
  } = useForm<Values>({
    defaultValues: {
      name: "",
      target_amount: 0,
      currency: baseCurrency,
      target_date: "",
      type: "other",
      priority: 3,
      initial_deposit: 0,
      auto_contribute_enabled: false,
      auto_contribute_amount: 0,
      auto_contribute_start_date: firstOfNextMonth(),
    },
  });

  useEffect(() => {
    if (!open) return;
    if (editing) {
      // Pre-fill auto-contribute from the active linked recurring (if any).
      // `next_due` carries the picked day-of-month forward, so we show it in
      // the date picker — the user can keep it or change it. The server
      // re-snaps next_due to first-of-next-month on every save, so the picker
      // is really a day-of-month picker dressed up as a date input.
      reset({
        name: editing.name,
        target_amount: editing.target_amount,
        currency: editing.currency,
        target_date: editing.target_date.slice(0, 10),
        type: editing.type,
        priority: editing.priority,
        initial_deposit: 0,
        auto_contribute_enabled: !!editing.auto_contribute,
        auto_contribute_amount: editing.auto_contribute?.amount ?? 0,
        auto_contribute_start_date: editing.auto_contribute
          ? editing.auto_contribute.next_due.slice(0, 10)
          : firstOfNextMonth(),
      });
    } else {
      reset({
        name: "",
        target_amount: 0,
        currency: baseCurrency,
        target_date: "",
        type: "other",
        priority: 3,
        initial_deposit: 0,
        auto_contribute_enabled: false,
        auto_contribute_amount: 0,
        auto_contribute_start_date: firstOfNextMonth(),
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, editing, baseCurrency]);

  const mutation = useMutation({
    mutationFn: async (values: Values) => {
      const isoDate = new Date(`${values.target_date}T12:00:00`).toISOString();
      if (isEditing && editing) {
        // Translate the form's tri-state auto-contribute UI into the
        // server's API:
        //   toggle ON  + had-auto-before → upsert (server updates amount/day)
        //   toggle ON  + no-auto-before  → upsert (server creates a recurring)
        //   toggle OFF + had-auto-before → false (server soft-deletes)
        //   toggle OFF + no-auto-before  → omit (no-op)
        const hadAuto = !!editing.auto_contribute;
        const wantAuto = values.auto_contribute_enabled;
        let autoChange: goalsApi.GoalUpdatePayload["auto_contribute"] = undefined;
        if (wantAuto && values.auto_contribute_start_date) {
          autoChange = {
            amount: values.auto_contribute_amount ?? 0,
            start_date: new Date(
              `${values.auto_contribute_start_date}T12:00:00`,
            ).toISOString(),
          };
        } else if (!wantAuto && hadAuto) {
          autoChange = false;
        }
        // Backend's GoalUpdate only accepts a subset; currency + initial_deposit
        // aren't editable post-create.
        return goalsApi.updateGoal(editing.id, {
          name: values.name.trim(),
          target_amount: values.target_amount,
          target_date: isoDate,
          type: values.type,
          priority: values.priority,
          ...(autoChange !== undefined ? { auto_contribute: autoChange } : {}),
        });
      }
      return goalsApi.createGoal({
        name: values.name.trim(),
        target_amount: values.target_amount,
        currency: values.currency as Currency,
        target_date: isoDate,
        type: values.type,
        priority: values.priority,
        initial_deposit: values.initial_deposit ?? 0,
        auto_contribute:
          values.auto_contribute_enabled && values.auto_contribute_start_date
            ? {
                amount: values.auto_contribute_amount ?? 0,
                start_date: new Date(
                  `${values.auto_contribute_start_date}T12:00:00`,
                ).toISOString(),
              }
            : undefined,
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.goals.all() });
      // Creating or editing a goal can also create/update/disable the
      // linked auto-contribute recurring_payments row, so /planned must
      // refetch — otherwise the user sees stale recurring data until
      // they navigate away and back.
      qc.invalidateQueries({ queryKey: qk.recurring.all() });
      onOpenChange(false);
    },
  });

  const type = watch("type");
  const priority = watch("priority");

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{isEditing ? "Edit goal" : "Create a goal"}</DialogTitle>
          <DialogDescription>
            {isEditing
              ? "Adjust the target, date, type, or priority."
              : "We'll work out how much to set aside each month."}
          </DialogDescription>
        </DialogHeader>

        <form
          id="goal-form"
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

          <div className="space-y-1.5">
            <Label htmlFor="g-name">Name</Label>
            <Input
              id="g-name"
              placeholder="Italy vacation"
              aria-invalid={!!errors.name}
              {...register("name")}
            />
            {errors.name && <p className="text-body-small text-danger">{errors.name.message}</p>}
          </div>

          <div className="grid grid-cols-3 gap-2">
            <div className="col-span-2 space-y-1.5">
              <Label htmlFor="g-amount">Target amount</Label>
              <Input
                id="g-amount"
                type="number"
                inputMode="decimal"
                step="0.01"
                placeholder="5000"
                aria-invalid={!!errors.target_amount}
                {...register("target_amount", { valueAsNumber: true })}
              />
              {errors.target_amount && (
                <p className="text-body-small text-danger">{errors.target_amount.message}</p>
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
                    disabled={isEditing}
                    className="flex h-10 w-full rounded-lg border border-border bg-surface px-2 text-body focus-ring disabled:opacity-60"
                  >
                    {SUPPORTED_CURRENCIES.map((c) => (
                      <option key={c}>{c}</option>
                    ))}
                  </select>
                )}
              />
              {isEditing && (
                <p className="text-uppercase-label uppercase text-text-muted">Locked after create</p>
              )}
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="g-due">Target date</Label>
            <Input
              id="g-due"
              type="date"
              aria-invalid={!!errors.target_date}
              {...register("target_date")}
            />
            {errors.target_date && (
              <p className="text-body-small text-danger">{errors.target_date.message}</p>
            )}
          </div>

          <div className="space-y-1.5">
            <Label>Type</Label>
            <div className="grid grid-cols-3 gap-1.5 sm:grid-cols-6">
              {TYPE_OPTIONS.map((t) => (
                <button
                  type="button"
                  key={t.id}
                  onClick={() => setValue("type", t.id, { shouldValidate: true })}
                  className={cn(
                    "flex flex-col items-center gap-1 rounded-lg border px-2 py-2 transition-all focus-ring",
                    type === t.id
                      ? "border-primary bg-primary-tint text-primary"
                      : "border-border bg-surface text-text-muted hover:border-outline",
                  )}
                >
                  <t.icon className="h-4 w-4" />
                  <span className="text-uppercase-label uppercase">{t.label}</span>
                </button>
              ))}
            </div>
          </div>

          <div className="space-y-1.5">
            <div className="flex items-baseline justify-between gap-2">
              <Label>Priority</Label>
              <span className="text-uppercase-label uppercase text-text-muted">
                1 = top priority · 5 = lowest
              </span>
            </div>
            <div className="flex gap-1.5">
              {[1, 2, 3, 4, 5].map((p) => (
                <button
                  type="button"
                  key={p}
                  onClick={() => setValue("priority", p)}
                  aria-label={`Priority ${p}`}
                  className={cn(
                    "h-9 w-9 rounded-full border transition-all focus-ring",
                    p <= priority
                      ? "border-primary bg-primary text-on-primary"
                      : "border-border bg-surface text-text-muted hover:border-outline",
                  )}
                >
                  {p}
                </button>
              ))}
            </div>
          </div>

          {!isEditing && (
            <div className="space-y-1.5">
              <Label htmlFor="g-deposit">Initial deposit (optional)</Label>
              <Input
                id="g-deposit"
                type="number"
                inputMode="decimal"
                step="0.01"
                placeholder="0"
                aria-invalid={!!errors.initial_deposit}
                {...register("initial_deposit", { valueAsNumber: true })}
              />
              {errors.initial_deposit && (
                <p className="text-body-small text-danger">{errors.initial_deposit.message}</p>
              )}
            </div>
          )}

          <div className="space-y-1.5 rounded-lg border border-border bg-surface-soft/40 p-3">
            <label className="flex cursor-pointer items-center justify-between gap-3">
              <div>
                <div className="text-body font-medium text-text-primary">
                  Auto-contribute monthly
                </div>
                <div className="text-uppercase-label uppercase text-text-muted">
                  Logged automatically as a transaction in the Goals category
                </div>
              </div>
              <input
                type="checkbox"
                className="h-5 w-5 cursor-pointer accent-primary"
                {...register("auto_contribute_enabled")}
              />
            </label>
            {watch("auto_contribute_enabled") && (
              <>
                <div className="grid grid-cols-2 gap-2 pt-2">
                  <div className="space-y-1">
                    <Label htmlFor="g-ac-amount">Monthly amount</Label>
                    <Input
                      id="g-ac-amount"
                      type="number"
                      inputMode="decimal"
                      step="0.01"
                      placeholder="100"
                      aria-invalid={!!errors.auto_contribute_amount}
                      {...register("auto_contribute_amount", { valueAsNumber: true })}
                    />
                    {errors.auto_contribute_amount && (
                      <p className="text-body-small text-danger">
                        {errors.auto_contribute_amount.message}
                      </p>
                    )}
                  </div>
                  <div className="space-y-1">
                    <Label htmlFor="g-ac-date">Starting on</Label>
                    <Input
                      id="g-ac-date"
                      type="date"
                      aria-invalid={!!errors.auto_contribute_start_date}
                      {...register("auto_contribute_start_date")}
                    />
                    {errors.auto_contribute_start_date && (
                      <p className="text-body-small text-danger">
                        {errors.auto_contribute_start_date.message}
                      </p>
                    )}
                  </div>
                </div>
                {isEditing && (
                  <p className="pt-1 text-uppercase-label uppercase text-text-muted">
                    Changes apply from next month — the day you pick is preserved.
                  </p>
                )}
              </>
            )}
          </div>
        </form>

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button form="goal-form" type="submit" variant="primary" disabled={mutation.isPending}>
            {mutation.isPending ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" /> Saving…
              </>
            ) : isEditing ? (
              "Save changes"
            ) : (
              "Create goal"
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
