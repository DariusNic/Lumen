import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Info, Loader2 } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { qk } from "@/lib/queryKeys";
import { formatMoney } from "@/lib/format";
import { parseApiError } from "@/api/client";
import { cn } from "@/lib/utils";
import * as portfolioApi from "@/api/portfolio.api";

interface Props {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  currentCashUsd: number;
}

/**
 * Adjust the paper portfolio's cash balance. Deliberately scoped to the
 * portfolio only — no transaction is logged in the PFM ledger, no Cash
 * account is debited. The dialog says so explicitly via the info banner
 * so the user understands they need to log a manual transaction if they
 * want to mirror the deposit/withdrawal as a real-money event.
 */
export function FundsDialog({ open, onOpenChange, currentCashUsd }: Props) {
  const qc = useQueryClient();
  const [direction, setDirection] = useState<portfolioApi.FundsDirection>("deposit");
  const [amountInput, setAmountInput] = useState("");

  // Reset state on open so reopening doesn't carry over the previous attempt.
  useEffect(() => {
    if (open) {
      setDirection("deposit");
      setAmountInput("");
    }
  }, [open]);

  const amount = Number(amountInput);
  const amountValid =
    amountInput !== "" && !Number.isNaN(amount) && amount > 0 && amount <= 1_000_000;
  const wouldOverWithdraw = direction === "withdrawal" && amount > currentCashUsd;
  const submitDisabled = !amountValid || wouldOverWithdraw;

  const projectedCash =
    direction === "deposit" ? currentCashUsd + amount : currentCashUsd - amount;

  const mutation = useMutation({
    mutationFn: () => portfolioApi.adjustFunds(direction, amount),
    onSuccess: () => {
      // Portfolio + the auto-tracked Paper Portfolio account hydration +
      // net worth all read from `portfolio.cash_usd`, so all three need
      // to refetch. Transactions / reports / budgets are deliberately
      // NOT invalidated — this op doesn't touch the PFM ledger.
      qc.invalidateQueries({ queryKey: qk.portfolio.all() });
      qc.invalidateQueries({ queryKey: qk.accounts.all() });
      qc.invalidateQueries({ queryKey: qk.networth.all() });
      onOpenChange(false);
    },
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Adjust trading funds</DialogTitle>
          <DialogDescription>
            Deposit or withdraw virtual cash directly to your paper portfolio.
          </DialogDescription>
        </DialogHeader>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (!submitDisabled && !mutation.isPending) mutation.mutate();
          }}
          className="space-y-md"
        >
          {mutation.isError && (
            <div
              role="alert"
              className="rounded-lg border border-danger/30 bg-danger/10 p-3 text-body-small text-danger"
            >
              {parseApiError(mutation.error)}
            </div>
          )}

          {/* Direction toggle — explicit Deposit / Withdraw rather than a signed
              amount, so a stray minus sign in the input can't flip intent. */}
          <div className="space-y-1.5">
            <Label>Direction</Label>
            <div className="inline-flex w-full rounded-lg border border-border bg-surface p-0.5">
              <button
                type="button"
                onClick={() => setDirection("deposit")}
                className={cn(
                  "flex-1 rounded-md px-3 py-1.5 text-body-small font-medium transition-colors",
                  direction === "deposit"
                    ? "bg-primary text-on-primary shadow-sm"
                    : "text-text-muted hover:text-text-primary",
                )}
              >
                Deposit
              </button>
              <button
                type="button"
                onClick={() => setDirection("withdrawal")}
                className={cn(
                  "flex-1 rounded-md px-3 py-1.5 text-body-small font-medium transition-colors",
                  direction === "withdrawal"
                    ? "bg-primary text-on-primary shadow-sm"
                    : "text-text-muted hover:text-text-primary",
                )}
              >
                Withdraw
              </button>
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="funds-amount">Amount (USD)</Label>
            <Input
              id="funds-amount"
              type="number"
              inputMode="decimal"
              step="0.01"
              min="0"
              placeholder="0.00"
              value={amountInput}
              onChange={(e) => setAmountInput(e.target.value)}
              autoFocus
              className="tabular"
            />
            {wouldOverWithdraw && (
              <p className="text-body-small text-danger">
                Can't withdraw more than your current trading cash ({formatMoney(currentCashUsd, "USD")}).
              </p>
            )}
            {amountInput !== "" && amount > 1_000_000 && (
              <p className="text-body-small text-danger">
                Amount above the $1,000,000 per-call cap.
              </p>
            )}
          </div>

          {/* Live preview of resulting cash so the user sees the consequence
              before confirming. */}
          <div className="rounded-lg border border-border bg-surface-soft p-3 text-body-small">
            <div className="flex items-center justify-between">
              <span className="text-text-muted">Current trading cash</span>
              <span className="tabular font-medium text-text-primary">
                {formatMoney(currentCashUsd, "USD")}
              </span>
            </div>
            <div className="mt-1 flex items-center justify-between">
              <span className="text-text-muted">After this adjustment</span>
              <span
                className={cn(
                  "tabular font-semibold",
                  amountValid && !wouldOverWithdraw
                    ? "text-text-primary"
                    : "text-text-muted",
                )}
              >
                {amountValid && !wouldOverWithdraw
                  ? formatMoney(projectedCash, "USD")
                  : "—"}
              </span>
            </div>
          </div>

          {/* Honest contract banner — these funds operations live entirely
              inside the paper portfolio. They do NOT touch the Cash account
              or write a row to the Transactions list. */}
          <div className="flex gap-2 rounded-lg border border-primary/30 bg-primary-tint/30 p-3 text-body-small text-text-primary">
            <Info className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
            <p>
              This adjustment changes only your paper portfolio's cash balance.
              It is <span className="font-semibold">not linked</span> to your
              Cash account and won't appear in the Transactions list. If you
              want to mirror this as a transaction between your Cash account and
              your Portfolio account, log it manually from the Transactions page.
            </p>
          </div>
        </form>

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={() => mutation.mutate()}
            disabled={submitDisabled || mutation.isPending}
          >
            {mutation.isPending ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" /> Saving…
              </>
            ) : direction === "deposit" ? (
              "Deposit"
            ) : (
              "Withdraw"
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
