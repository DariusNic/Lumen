import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
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
import { formatMoneyWithBase } from "@/components/shared/MoneyWithBase";
import { useCurrency } from "@/hooks/useCurrency";
import { useFxRate } from "@/hooks/useFxRate";
import { parseApiError } from "@/api/client";
import { cn } from "@/lib/utils";
import * as portfolioApi from "@/api/portfolio.api";

interface Props {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  ticker: string;
  lastClose: number | null;
  /** Pre-select Buy or Sell. Defaults to Buy. */
  initialSide?: "buy" | "sell";
}

export function TradeDialog({
  open,
  onOpenChange,
  ticker,
  lastClose,
  initialSide = "buy",
}: Props) {
  const qc = useQueryClient();
  const [side, setSide] = useState<"buy" | "sell">(initialSide);
  const [qtyInput, setQtyInput] = useState("1");
  const baseCurrency = useCurrency();
  const usdToBase = useFxRate("USD", baseCurrency);
  const moneyUsd = (n: number) =>
    formatMoneyWithBase(n, "USD", baseCurrency, usdToBase);

  // Reset form state on open so reopening the dialog never carries over
  // the previous attempt's qty / side.
  useEffect(() => {
    if (open) {
      setSide(initialSide);
      setQtyInput("1");
    }
  }, [open, initialSide]);

  const portfolioQuery = useQuery({
    queryKey: qk.portfolio.current(),
    queryFn: portfolioApi.getPortfolio,
    enabled: open,
  });
  const portfolio = portfolioQuery.data;
  const heldQty = portfolio?.holdings.find((h) => h.ticker === ticker)?.qty ?? 0;
  const cash = portfolio?.cash_usd ?? 0;
  const qty = Number(qtyInput);
  const qtyValid = Number.isFinite(qty) && qty > 0;
  const total = qtyValid && lastClose != null ? qty * lastClose : null;
  const cashShortfall = side === "buy" && total != null && total > cash;
  const sharesShortfall = side === "sell" && qtyValid && qty > heldQty;
  const canSubmit = qtyValid && !cashShortfall && !sharesShortfall && lastClose != null;

  const mutation = useMutation({
    mutationFn: () =>
      side === "buy"
        ? portfolioApi.buy(ticker, qty)
        : portfolioApi.sell(ticker, qty),
    onSuccess: () => {
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
          <DialogTitle>Paper trade {ticker}</DialogTitle>
          <DialogDescription>
            Executes at the latest close ({lastClose != null ? moneyUsd(lastClose) : "—"}).
            No commissions, no slippage.
          </DialogDescription>
        </DialogHeader>

        {/* Side selector */}
        <div className="flex gap-1 rounded-lg bg-surface-variant p-1">
          {(["buy", "sell"] as const).map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setSide(s)}
              className={cn(
                "flex-1 rounded-md py-2 text-body-small font-semibold uppercase transition-all focus-ring",
                side === s
                  ? s === "buy"
                    ? "bg-success text-white"
                    : "bg-danger text-white"
                  : "text-text-muted hover:text-text-primary",
              )}
            >
              {s}
            </button>
          ))}
        </div>

        <div className="space-y-md">
          <div className="space-y-1.5">
            <Label htmlFor="trade-qty">Quantity</Label>
            <Input
              id="trade-qty"
              type="number"
              step="0.01"
              min="0"
              inputMode="decimal"
              value={qtyInput}
              onChange={(e) => setQtyInput(e.target.value)}
              className="tabular"
            />
            {side === "sell" && (
              <p className="text-uppercase-label uppercase text-text-muted">
                You hold <span className="tabular text-text-primary">{heldQty}</span> share
                {heldQty === 1 ? "" : "s"}
              </p>
            )}
          </div>

          {/* Summary */}
          <div className="rounded-lg border border-border bg-surface-soft p-3 space-y-1 text-body-small">
            <Row label="Side" value={side === "buy" ? "Buy" : "Sell"} mono />
            <Row label="Quantity" value={qtyValid ? String(qty) : "—"} mono />
            <Row
              label="Price (last close)"
              value={lastClose != null ? moneyUsd(lastClose) : "—"}
            />
            <Row
              label={side === "buy" ? "Cash needed" : "Cash credited"}
              value={total != null ? moneyUsd(total) : "—"}
              tone={
                cashShortfall ? "danger"
                : side === "sell" && qtyValid ? "success"
                : "default"
              }
            />
            <Row
              label="Cash on hand"
              value={moneyUsd(cash)}
              tone={cashShortfall ? "danger" : "default"}
            />
          </div>

          {(cashShortfall || sharesShortfall || mutation.isError) && (
            <div role="alert" className="rounded-lg border border-danger/30 bg-danger/10 p-3 text-body-small text-danger">
              {cashShortfall && "Not enough cash for this buy."}
              {sharesShortfall && `You only hold ${heldQty} share${heldQty === 1 ? "" : "s"}.`}
              {mutation.isError && parseApiError(mutation.error)}
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button
            variant={side === "buy" ? "primary" : "danger"}
            onClick={() => mutation.mutate()}
            disabled={!canSubmit || mutation.isPending}
          >
            {mutation.isPending ? (
              <><Loader2 className="h-4 w-4 animate-spin" /> Executing…</>
            ) : (
              `${side === "buy" ? "Buy" : "Sell"} ${qtyValid ? qty : ""} ${ticker}`.trim()
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}


function Row({
  label,
  value,
  mono = false,
  tone = "default",
}: {
  label: string;
  value: string;
  mono?: boolean;
  tone?: "default" | "success" | "danger";
}) {
  return (
    <div className="flex justify-between">
      <span className="text-text-muted">{label}</span>
      <span
        className={cn(
          "tabular",
          mono && "font-mono",
          tone === "success" && "text-success font-semibold",
          tone === "danger" && "text-danger font-semibold",
        )}
      >
        {value}
      </span>
    </div>
  );
}
