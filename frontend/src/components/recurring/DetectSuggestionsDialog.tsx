import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Loader2, Sparkles, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { qk } from "@/lib/queryKeys";
import { formatMoney } from "@/lib/format";
import { parseApiError } from "@/api/client";
import * as recApi from "@/api/recurring.api";
import { cn } from "@/lib/utils";

interface Props {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  /** Result of POST /api/recurring/detect; null = no scan run yet. */
  result: recApi.DetectionResult | null;
  /** Open the create-form pre-filled from a suggestion. */
  onConfirm: (suggestion: recApi.DetectionSuggestion) => void;
}

export function DetectSuggestionsDialog({ open, onOpenChange, result, onConfirm }: Props) {
  const qc = useQueryClient();

  // Track per-suggestion dismissal locally so the user gets immediate feedback
  // (we don't store dismissals in the DB — the next scan would re-surface them
  // and that's the correct behavior; user can tweak the rules.py upstream).
  // We simply hide the row from the list.

  const dismissMutation = useMutation({
    mutationFn: async () => undefined,
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.recurring.all() }),
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-primary" />
            Detected recurring patterns
          </DialogTitle>
          <DialogDescription>
            We scanned your last 90 days of transactions for similarly-named merchants that recur
            on a steady cadence and a steady amount. Confirm the ones you actually want tracked —
            nothing is added to your planned payments automatically.
          </DialogDescription>
        </DialogHeader>

        {result == null ? (
          <div className="flex items-center gap-2 py-md text-body-small text-text-muted">
            <Loader2 className="h-4 w-4 animate-spin" /> Scanning your transactions…
          </div>
        ) : (
          <>
            <div className="rounded-lg border border-border bg-surface-soft p-3 text-body-small text-text-muted">
              Scanned <strong className="text-text-primary">{result.transactions_scanned}</strong>{" "}
              transactions, grouped them into{" "}
              <strong className="text-text-primary">{result.clusters_found}</strong>{" "}
              merchant{result.clusters_found === 1 ? "" : "s"} —{" "}
              <strong className="text-text-primary">{result.suggestions.length}</strong>{" "}
              {result.suggestions.length === 1 ? "looks" : "look"} like recurring patterns.
            </div>

            {result.suggestions.length === 0 ? (
              <div className="rounded-xl border border-dashed border-border bg-surface-soft py-lg px-md text-center">
                <p className="text-body-small font-medium text-text-primary">
                  Nothing new to suggest
                </p>
                <p className="mt-1 text-body-small text-text-muted">
                  Either you've already confirmed all your recurring patterns, or you don't have
                  enough transaction history yet for the algorithm to be confident.
                </p>
              </div>
            ) : (
              <ul className="space-y-2">
                {result.suggestions.map((s) => (
                  <li
                    key={s.merchant_pattern + s.last_seen}
                    className="flex items-center gap-3 rounded-xl border border-border bg-surface p-3"
                  >
                    <div
                      className={cn(
                        "flex h-9 w-9 shrink-0 items-center justify-center rounded-full",
                        s.is_income ? "bg-success/15 text-success" : "bg-primary-tint text-primary",
                      )}
                    >
                      <Sparkles className="h-4 w-4" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                        <span className="font-medium text-text-primary">{s.merchant_pattern}</span>
                        <span className="text-uppercase-label uppercase text-text-muted">
                          {s.frequency} · {s.occurrences}× in last 90d
                        </span>
                      </div>
                      <div className="text-body-small text-text-muted">
                        ~
                        <span className="tabular text-text-primary">
                          {formatMoney(s.average_amount, s.currency)}
                        </span>{" "}
                        per occurrence · last seen{" "}
                        {new Date(s.last_seen).toLocaleDateString("en-US", {
                          month: "short",
                          day: "numeric",
                        })}
                      </div>
                    </div>
                    <div className="flex shrink-0 gap-1">
                      <Button variant="primary" size="sm" onClick={() => onConfirm(s)}>
                        <CheckCircle2 className="h-3.5 w-3.5" /> Confirm
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => dismissMutation.mutate()}
                        aria-label="Dismiss suggestion"
                      >
                        <X className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  </li>
                ))}
              </ul>
            )}

            {dismissMutation.isError && (
              <div role="alert" className="text-body-small text-danger">
                {parseApiError(dismissMutation.error)}
              </div>
            )}
          </>
        )}

        <DialogFooter>
          <Button variant="primary" onClick={() => onOpenChange(false)}>
            Done
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
