import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";
import { Loader2, Sparkles } from "lucide-react";
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
import { parseApiError } from "@/api/client";
import { formatMoney } from "@/lib/format";
import * as goalsApi from "@/api/goals.api";

const schema = z.object({
  amount: z.number().positive("Must be positive"),
  when: z.string().min(1, "Required"),
});
type Values = z.infer<typeof schema>;

interface Props {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  goal: goalsApi.Goal | null;
}

export function ContributeDialog({ open, onOpenChange, goal }: Props) {
  const qc = useQueryClient();
  const todayIso = new Date().toISOString().slice(0, 10);

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<Values>({
    defaultValues: { amount: 0, when: todayIso },
  });

  useEffect(() => {
    if (open) reset({ amount: 0, when: todayIso });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const mutation = useMutation({
    mutationFn: (values: Values) => {
      if (!goal) throw new Error("No goal");
      // Parse picked date as midnight UTC of that day. Earlier code used
      // `T12:00:00` without a timezone marker, which JS interpreted as noon
      // *local* time — for any user east of UTC (e.g. Romania UTC+3), that
      // shifts to 09:00 UTC, which is still in the future for morning
      // contributions and the backend rejects the resulting transaction
      // (`Transaction date can't be in the future`). The 500 response then
      // happens AFTER `goal.saved_amount` was already incremented inside
      // `_do_contribute`, silently desyncing the goal from the ledger.
      // Midnight-UTC of a "today or earlier" date is always ≤ now, so no
      // future-date validation issue.
      const whenUtc = new Date(values.when).toISOString();
      return goalsApi.contributeToGoal(goal.id, {
        amount: values.amount,
        when: whenUtc,
      });
    },
    onSuccess: () => {
      // A contribution writes a transaction (source="goal_contribution",
      // category="Goals") that flows through 4+ surfaces. Invalidate
      // everything that derives from transactions so the Dashboard KPI,
      // Transactions list, Net Worth, and category sums refresh instead
      // of staying stale until manual reload.
      qc.invalidateQueries({ queryKey: qk.goals.all() });
      qc.invalidateQueries({ queryKey: qk.transactions.all() });
      qc.invalidateQueries({ queryKey: qk.reports.all() });
      qc.invalidateQueries({ queryKey: qk.accounts.all() });
      qc.invalidateQueries({ queryKey: qk.networth.all() });
      // A contribution that pushes the goal to (or past) target closes the
      // linked auto-contribute recurring via `_close_linked_recurring`, so
      // /planned must refetch — otherwise the entry stays visible.
      qc.invalidateQueries({ queryKey: qk.recurring.all() });
      onOpenChange(false);
    },
  });

  const remaining = goal ? Math.max(0, goal.target_amount - goal.saved_amount) : 0;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Contribute to {goal?.name ?? "goal"}</DialogTitle>
          <DialogDescription>
            Logs the contribution and bumps your progress. The goal's status / monthly pace
            recalculates immediately.
          </DialogDescription>
        </DialogHeader>

        {goal && (
          <div className="rounded-lg border border-border bg-surface-soft p-3 text-body-small">
            <div className="flex items-center justify-between">
              <span className="text-text-muted">Saved so far</span>
              <span className="font-semibold tabular text-text-primary">
                {formatMoney(goal.saved_amount, goal.currency)}
              </span>
            </div>
            <div className="mt-1 flex items-center justify-between">
              <span className="text-text-muted">Target</span>
              <span className="font-semibold tabular text-text-primary">
                {formatMoney(goal.target_amount, goal.currency)}
              </span>
            </div>
            <div className="mt-1 flex items-center justify-between">
              <span className="text-text-muted">Remaining</span>
              <span className="font-semibold tabular text-primary">
                {formatMoney(remaining, goal.currency)}
              </span>
            </div>
          </div>
        )}

        <form
          id="contribute-form"
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
            <Label htmlFor="c-amount">Amount</Label>
            <div className="flex items-stretch gap-2">
              <Input
                id="c-amount"
                type="number"
                step="0.01"
                inputMode="decimal"
                className="tabular"
                aria-invalid={!!errors.amount}
                {...register("amount", { valueAsNumber: true })}
              />
              <span className="flex items-center rounded-lg border border-border bg-surface-soft px-3 text-body-small font-medium text-text-muted">
                {goal?.currency ?? ""}
              </span>
            </div>
            {errors.amount && (
              <p className="text-body-small text-danger">{errors.amount.message}</p>
            )}
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="c-date">When</Label>
            <Input
              id="c-date"
              type="date"
              max={todayIso}
              aria-invalid={!!errors.when}
              {...register("when")}
            />
            {errors.when && (
              <p className="text-body-small text-danger">{errors.when.message}</p>
            )}
          </div>

          <p className="rounded-lg bg-primary-tint/40 p-3 text-body-small text-primary">
            <Sparkles className="mr-1.5 inline h-3.5 w-3.5" />
            Every contribution is logged so your Reports page can chart progress over time.
          </p>
        </form>

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button form="contribute-form" type="submit" variant="primary" disabled={mutation.isPending}>
            {mutation.isPending ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" /> Saving…
              </>
            ) : (
              "Add contribution"
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
