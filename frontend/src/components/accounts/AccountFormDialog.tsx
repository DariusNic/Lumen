import { useEffect } from "react";
import { useForm, Controller } from "react-hook-form";
import { useMutation, useQueryClient } from "@tanstack/react-query";
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
import * as accountsApi from "@/api/accounts.api";

const ASSET_TYPES: accountsApi.AccountType[] = [
  "cash", "savings", "investment", "real_estate", "vehicle", "other_asset",
];
const LIABILITY_TYPES: accountsApi.AccountType[] = [
  "credit", "loan", "mortgage", "other_liability",
];

const TYPE_LABEL: Record<accountsApi.AccountType, string> = {
  cash: "Cash",
  savings: "Savings",
  investment: "Investment",
  real_estate: "Real estate",
  vehicle: "Vehicle",
  other_asset: "Other asset",
  credit: "Credit card",
  loan: "Loan",
  mortgage: "Mortgage",
  other_liability: "Other liability",
};

const schema = z.object({
  name: z.string().min(1, "Required").max(80),
  type: z.enum([
    "cash", "savings", "investment", "real_estate", "vehicle", "other_asset",
    "credit", "loan", "mortgage", "other_liability",
  ]),
  balance: z.number().nonnegative("Balance can't be negative"),
  currency: z.enum(SUPPORTED_CURRENCIES),
  notes: z.string().max(400).optional(),
});
type Values = z.infer<typeof schema>;

interface Props {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  editing?: accountsApi.Account | null;
}

export function AccountFormDialog({ open, onOpenChange, editing }: Props) {
  const baseCurrency = useCurrency();
  const qc = useQueryClient();
  const isEditing = !!editing;

  const {
    register,
    handleSubmit,
    control,
    reset,
    formState: { errors },
  } = useForm<Values>({
    defaultValues: {
      name: "",
      type: "savings",
      balance: 0,
      currency: baseCurrency,
      notes: "",
    },
  });

  useEffect(() => {
    if (!open) return;
    if (editing) {
      reset({
        name: editing.name,
        type: editing.type,
        balance: editing.balance,
        currency: editing.currency,
        notes: editing.notes ?? "",
      });
    } else {
      reset({
        name: "",
        type: "savings",
        balance: 0,
        currency: baseCurrency,
        notes: "",
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, editing, baseCurrency]);

  const mutation = useMutation({
    mutationFn: async (values: Values) => {
      if (isEditing && editing) {
        return accountsApi.updateAccount(editing.id, {
          name: values.name.trim(),
          type: values.type,
          balance: values.balance,
          currency: values.currency as Currency,
          notes: values.notes?.trim() || null,
        });
      }
      return accountsApi.createAccount({
        name: values.name.trim(),
        type: values.type,
        balance: values.balance,
        currency: values.currency as Currency,
        notes: values.notes?.trim() || null,
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.accounts.all() });
      onOpenChange(false);
    },
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{isEditing ? "Edit account" : "Add an account"}</DialogTitle>
          <DialogDescription>
            Anything you own (cash, savings, real estate, vehicle) or owe (credit, loan,
            mortgage). Balances feed your net worth.
          </DialogDescription>
        </DialogHeader>

        <form
          id="acc-form"
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
            <Label htmlFor="a-name">Name</Label>
            <Input
              id="a-name"
              placeholder="Apartment Bucuresti"
              aria-invalid={!!errors.name}
              {...register("name")}
            />
            {errors.name && <p className="text-body-small text-danger">{errors.name.message}</p>}
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div className="space-y-1.5">
              <Label htmlFor="a-type">Type</Label>
              <Controller
                name="type"
                control={control}
                render={({ field }) => (
                  <select
                    {...field}
                    id="a-type"
                    className="flex h-10 w-full rounded-lg border border-border bg-surface px-3 text-body focus-ring"
                  >
                    <optgroup label="Assets">
                      {ASSET_TYPES.map((t) => (
                        <option key={t} value={t}>
                          {TYPE_LABEL[t]}
                        </option>
                      ))}
                    </optgroup>
                    <optgroup label="Liabilities">
                      {LIABILITY_TYPES.map((t) => (
                        <option key={t} value={t}>
                          {TYPE_LABEL[t]}
                        </option>
                      ))}
                    </optgroup>
                  </select>
                )}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="a-balance">Balance</Label>
              <Input
                id="a-balance"
                type="number"
                step="0.01"
                inputMode="decimal"
                className="tabular"
                aria-invalid={!!errors.balance}
                {...register("balance", { valueAsNumber: true })}
              />
              {errors.balance && (
                <p className="text-body-small text-danger">{errors.balance.message}</p>
              )}
            </div>
          </div>

          <div className="space-y-1.5">
            <Label>Currency</Label>
            <Controller
              name="currency"
              control={control}
              render={({ field }) => (
                <select
                  {...field}
                  className="flex h-10 w-32 rounded-lg border border-border bg-surface px-3 text-body focus-ring"
                >
                  {SUPPORTED_CURRENCIES.map((c) => (
                    <option key={c}>{c}</option>
                  ))}
                </select>
              )}
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="a-notes">Notes (optional)</Label>
            <textarea
              id="a-notes"
              rows={2}
              placeholder="Estimated market value as of …"
              className="flex w-full resize-none rounded-lg border border-border bg-surface p-3 text-body focus-ring"
              {...register("notes")}
            />
          </div>
        </form>

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button form="acc-form" type="submit" variant="primary" disabled={mutation.isPending}>
            {mutation.isPending ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" /> Saving…
              </>
            ) : isEditing ? (
              "Save changes"
            ) : (
              "Add account"
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
