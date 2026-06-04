import { useEffect } from "react";
import { useForm, Controller } from "react-hook-form";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { z } from "zod";
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
import * as txApi from "@/api/transactions.api";

const schema = z.object({
  date: z
    .string()
    .min(1, "Required")
    .refine(
      (s) => {
        const picked = new Date(`${s}T00:00:00`);
        const todayEnd = new Date();
        todayEnd.setHours(23, 59, 59, 999);
        return picked.getTime() <= todayEnd.getTime();
      },
      { message: "Date can't be in the future" },
    ),
  kind: z.enum(["expense", "income"]),
  amount: z.number().positive("Amount must be positive"),
  currency: z.enum(SUPPORTED_CURRENCIES),
  description: z.string().min(1, "Required").max(400),
  merchant: z.string().max(200).optional(),
  category_id: z.string().optional(),
});
type Values = z.infer<typeof schema>;

interface Props {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  /** When provided, the dialog opens in edit mode and pre-fills from this row. */
  editing?: txApi.Transaction | null;
}

export function TransactionFormDialog({ open, onOpenChange, editing }: Props) {
  const baseCurrency = useCurrency();
  const qc = useQueryClient();

  const categoriesQuery = useQuery({
    queryKey: qk.categories.all(),
    queryFn: catApi.listCategories,
    enabled: open,
  });

  const isEditing = !!editing;
  const todayIso = new Date().toISOString().slice(0, 10);

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
      date: todayIso,
      kind: "expense",
      amount: 0,
      currency: baseCurrency,
      description: "",
      merchant: "",
      category_id: "",
    },
  });

  // When the dialog opens (or `editing` changes), reset the form to the right values.
  useEffect(() => {
    if (!open) return;
    if (editing) {
      reset({
        date: editing.date.slice(0, 10),
        kind: editing.amount >= 0 ? "income" : "expense",
        amount: Math.abs(editing.amount),
        currency: editing.currency,
        description: editing.description,
        merchant: editing.merchant ?? "",
        category_id: editing.category_id ?? "",
      });
    } else {
      reset({
        date: todayIso,
        kind: "expense",
        amount: 0,
        currency: baseCurrency,
        description: "",
        merchant: "",
        category_id: "",
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, editing, baseCurrency]);

  const mutation = useMutation({
    mutationFn: async (values: Values) => {
      // Always start from the absolute value: the user-typed sign (if any)
      // is dropped so the expense/income toggle is the single source of
      // truth for sign. Without this, typing "-77.50" while the toggle is
      // on "expense" double-negates to +77.50 (income).
      const magnitude = Math.abs(values.amount);
      const signed = values.kind === "expense" ? -magnitude : magnitude;
      // UTC midnight of the picked day. Using local-noon (the previous
      // version) silently shifted today's date to ~09:00 UTC, which is in
      // the future when the user opens the app before noon UTC — the
      // backend's `_reject_future` validator then rejects it as 422
      // "Invalid request". Midnight UTC is always ≤ utcnow() for today
      // or any earlier day, so it never trips the validator.
      const isoDate = new Date(`${values.date}T00:00:00Z`).toISOString();
      const payload = {
        date: isoDate,
        amount: signed,
        currency: values.currency as Currency,
        description: values.description.trim(),
        merchant: values.merchant?.trim() || null,
        category_id: values.category_id || null,
      };
      if (isEditing && editing) {
        return txApi.updateTransaction(editing.id, payload);
      }
      return txApi.createTransaction(payload);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.transactions.all() });
      qc.invalidateQueries({ queryKey: qk.reports.all() });
      qc.invalidateQueries({ queryKey: qk.accounts.all() });
      onOpenChange(false);
    },
  });

  const kind = watch("kind");

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{isEditing ? "Edit transaction" : "Add a transaction"}</DialogTitle>
          <DialogDescription>
            {isEditing
              ? "Update the details below. Changing the category logs a correction so the categorizer learns from it."
              : "Manually record one row. For bulk loads, use Import CSV."}
          </DialogDescription>
        </DialogHeader>

        <form
          id="tx-form"
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

          {/* Kind toggle */}
          <div className="grid grid-cols-2 gap-2 rounded-lg bg-surface-variant p-1">
            {(["expense", "income"] as const).map((k) => (
              <button
                key={k}
                type="button"
                onClick={() => setValue("kind", k)}
                className={
                  "rounded-md py-2 text-body-small font-semibold uppercase transition-all focus-ring " +
                  (kind === k
                    ? k === "expense"
                      ? "bg-danger text-white"
                      : "bg-success text-white"
                    : "text-text-muted hover:text-text-primary")
                }
              >
                {k}
              </button>
            ))}
          </div>

          <div className="grid grid-cols-2 gap-md">
            <div className="space-y-1.5">
              <Label htmlFor="tx-date">Date</Label>
              <Input
                id="tx-date"
                type="date"
                max={todayIso}
                {...register("date")}
              />
              {errors.date && <p className="text-body-small text-danger">{errors.date.message}</p>}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="tx-amount">Amount</Label>
              <div className="flex gap-2">
                <Input
                  id="tx-amount"
                  type="number"
                  step="0.01"
                  min="0"
                  inputMode="decimal"
                  className="tabular"
                  aria-invalid={!!errors.amount}
                  {...register("amount", { valueAsNumber: true })}
                />
                <Controller
                  name="currency"
                  control={control}
                  render={({ field }) => (
                    <select
                      {...field}
                      className="flex h-10 w-24 rounded-lg border border-border bg-surface px-2 text-body focus-ring"
                    >
                      {SUPPORTED_CURRENCIES.map((c) => (
                        <option key={c}>{c}</option>
                      ))}
                    </select>
                  )}
                />
              </div>
              {errors.amount && (
                <p className="text-body-small text-danger">{errors.amount.message}</p>
              )}
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="tx-description">Description</Label>
            <Input
              id="tx-description"
              placeholder="CARREFOUR Baneasa"
              aria-invalid={!!errors.description}
              {...register("description")}
            />
            {errors.description && (
              <p className="text-body-small text-danger">{errors.description.message}</p>
            )}
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="tx-merchant">Merchant (optional)</Label>
            <Input id="tx-merchant" placeholder="Carrefour" {...register("merchant")} />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="tx-category">Category</Label>
            <Controller
              name="category_id"
              control={control}
              render={({ field }) => (
                <select
                  id="tx-category"
                  {...field}
                  className="flex h-10 w-full rounded-lg border border-border bg-surface px-3 text-body focus-ring"
                >
                  <option value="">Auto-categorize from description</option>
                  {(categoriesQuery.data ?? []).map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              )}
            />
            <p className="text-uppercase-label uppercase text-text-muted">
              Leaving this blank runs the rules-based categorizer.
            </p>
          </div>
        </form>

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button form="tx-form" type="submit" variant="primary" disabled={mutation.isPending}>
            {mutation.isPending ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" /> Saving…
              </>
            ) : isEditing ? (
              "Save changes"
            ) : (
              "Add transaction"
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
