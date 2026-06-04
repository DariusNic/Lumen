import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bar,
  BarChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { ChevronDown, Loader2, Pencil, Wallet } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { SectionCard } from "@/components/shared/SectionCard";
import { MonthPicker, type YearMonth } from "@/components/shared/MonthPicker";
import {
  Sheet,
  SheetContent,
  SheetFooter,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { Input } from "@/components/ui/input";
import { useCurrency } from "@/hooks/useCurrency";
import { qk } from "@/lib/queryKeys";
import { formatMoney } from "@/lib/format";
import { parseApiError } from "@/api/client";
import * as catApi from "@/api/categories.api";
import * as reportsApi from "@/api/reports.api";
import { cn } from "@/lib/utils";

const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

function boundsFor(ym: YearMonth) {
  const start = new Date(ym.year, ym.month - 1, 1).toISOString().slice(0, 10);
  const end = new Date(ym.year, ym.month, 0).toISOString().slice(0, 10);
  return { start, end };
}

interface Row {
  category: catApi.Category;
  spent: number;
  txCount: number;
  pct: number;
  bucket: "over" | "trending" | "ok";
}

export default function BudgetPage() {
  const currency = useCurrency();
  const [month, setMonth] = useState<YearMonth>(MonthPicker.thisMonth());
  const [expanded, setExpanded] = useState<string | null>(null);
  const { start, end } = boundsFor(month);
  const monthHeading = `${MONTH_NAMES[month.month - 1]} ${month.year}`;

  const categoriesQuery = useQuery({
    queryKey: qk.categories.all(),
    queryFn: catApi.listCategories,
  });
  const spendingQuery = useQuery({
    queryKey: qk.reports.spending(start, end),
    queryFn: () => reportsApi.getSpendingReport(start, end),
  });
  const monthlyQuery = useQuery({
    queryKey: qk.reports.monthly(6),
    queryFn: () => reportsApi.getMonthlyReport(6),
  });

  const rows: Row[] = useMemo(() => {
    const cats = categoriesQuery.data ?? [];
    const spendingByCatId = new Map<string, { total: number; count: number }>();
    for (const it of spendingQuery.data?.items ?? []) {
      if (it.category_id) {
        spendingByCatId.set(it.category_id, { total: it.total, count: it.count });
      }
    }
    return cats
      .map((c) => {
        const sp = spendingByCatId.get(c.id);
        const spent = sp?.total ?? 0;
        const txCount = sp?.count ?? 0;
        const budget = c.monthly_budget;
        // Treat a zero budget as a real (zero) budget, not as
        // "unconfigured" — every category starts at 0 by default and
        // the user edits up from there. A row is "over" the moment
        // spending exceeds the configured budget (always true when
        // budget=0 and any money was spent).
        const pct = budget > 0 ? (spent / budget) * 100 : spent > 0 ? Infinity : 0;
        let bucket: Row["bucket"] = "ok";
        if (spent > budget) bucket = "over";
        else if (budget > 0 && pct > 80) bucket = "trending";
        return { category: c, spent, txCount, pct, bucket };
      })
      .sort((a, b) => {
        // Over-budget first (largest absolute overshoot, in money — keeps
        // the order honest when budget=0 makes pct=Infinity for many
        // rows), then trending, then OK. Alphabetical within bucket.
        const orderOf = (b: Row["bucket"]) =>
          b === "over" ? 0 : b === "trending" ? 1 : 2;
        if (orderOf(a.bucket) !== orderOf(b.bucket)) return orderOf(a.bucket) - orderOf(b.bucket);
        if (a.bucket === "over") return (b.spent - b.category.monthly_budget) - (a.spent - a.category.monthly_budget);
        return a.category.name.localeCompare(b.category.name);
      });
  }, [categoriesQuery.data, spendingQuery.data]);

  const totalSpent = rows.reduce((s, r) => s + r.spent, 0);
  const totalBudget = rows.reduce((s, r) => s + r.category.monthly_budget, 0);
  const remaining = totalBudget - totalSpent;
  const totalPct = totalBudget > 0 ? Math.round((totalSpent / totalBudget) * 100) : 0;

  const groups = {
    over: rows.filter((r) => r.bucket === "over"),
    trending: rows.filter((r) => r.bucket === "trending"),
    ok: rows.filter((r) => r.bucket === "ok"),
  };

  // Trailing 6-month spent vs total budget for the right-hand chart.
  const history = (monthlyQuery.data?.months ?? []).map((m) => ({
    label: `${MONTH_NAMES[m.month - 1].slice(0, 3)} ${String(m.year).slice(-2)}`,
    spent: m.expense,
    budget: totalBudget,
  }));

  return (
    <div className="space-y-lg animate-fade-in">
      <header className="flex flex-wrap items-center justify-between gap-md">
        <div>
          <h1 className="text-h2 font-h2 text-text-primary">Budget</h1>
          <p className="text-body-small text-text-muted">{monthHeading}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <MonthPicker value={month} onChange={setMonth} />
          <SetBudgetsSheet />
        </div>
      </header>

      {/* Summary */}
      <SectionCard>
        <div className="grid items-center gap-lg md:grid-cols-2">
            <div>
              <div className="text-uppercase-label uppercase text-text-muted">
                Spent vs. budget · {monthHeading}
              </div>
              <div className="mt-1 text-h2 font-h2 tabular">
                {formatMoney(totalSpent, currency)}{" "}
                <span className="text-text-muted">/ {formatMoney(totalBudget, currency)}</span>
              </div>
              <Progress
                className="mt-3"
                value={Math.min(100, totalPct)}
                tone={totalPct >= 100 ? "danger" : totalPct > 80 ? "warning" : "default"}
              />
              <div className="mt-2 text-body-small text-text-muted">
                {remaining >= 0 ? (
                  <>
                    {formatMoney(remaining, currency)} remaining ({100 - totalPct}%)
                  </>
                ) : (
                  <span className="text-danger">
                    Over by {formatMoney(Math.abs(remaining), currency)} ({totalPct - 100}%)
                  </span>
                )}
              </div>
            </div>
            <div className="h-32">
              {history.length === 0 ? (
                <div className="flex h-full items-center justify-center text-uppercase-label uppercase text-text-muted">
                  Need a few months of history
                </div>
              ) : (
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={history} margin={{ top: 0, right: 4, left: 0, bottom: 0 }}>
                    <XAxis
                      dataKey="label"
                      axisLine={false}
                      tickLine={false}
                      tick={{ fontSize: 11, fill: "rgb(var(--text-muted))" }}
                    />
                    <YAxis hide />
                    <Tooltip
                      contentStyle={{
                        borderRadius: 8,
                        border: "1px solid rgb(var(--border))",
                        fontSize: 12,
                      }}
                      formatter={(v: number) => formatMoney(v, currency)}
                    />
                    <Bar dataKey="spent" fill="rgb(239 68 68)" radius={[4, 4, 0, 0]} />
                    <Bar dataKey="budget" fill="rgb(16 185 129)" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </div>
        </div>
      </SectionCard>

      {/* Loading */}
      {(categoriesQuery.isLoading || spendingQuery.isLoading) && (
        <div className="flex items-center justify-center gap-2 py-md text-body-small text-text-muted">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading…
        </div>
      )}

      {/* Groups */}
      {(["over", "trending", "ok"] as const).map((g) => {
          const list =
            g === "over" ? groups.over
            : g === "trending" ? groups.trending
            : groups.ok;
          if (!list.length) return null;
          const label =
            g === "over" ? "Over budget"
            : g === "trending" ? "On track to exceed"
            : "Under control";
          return (
            <section key={g}>
              <h2 className="mb-2 px-1 text-uppercase-label uppercase text-text-muted">{label}</h2>
              <SectionCard noPadding>
                <ul className="divide-y divide-border">
                  {list.map((r) => (
                    <CategoryRow
                      key={r.category.id}
                      row={r}
                      currency={currency}
                      month={month}
                      expanded={expanded === r.category.id}
                      onToggle={() =>
                        setExpanded((cur) => (cur === r.category.id ? null : r.category.id))
                      }
                    />
                  ))}
                </ul>
              </SectionCard>
            </section>
          );
        })}
    </div>
  );
}

function CategoryRow({
  row,
  currency,
  month,
  expanded,
  onToggle,
}: {
  row: Row;
  currency: "RON" | "EUR" | "USD";
  month: YearMonth;
  expanded: boolean;
  onToggle: () => void;
}) {
  const { category: c, spent, txCount, pct, bucket } = row;
  const tone = bucket === "over" ? "danger" : bucket === "trending" ? "warning" : "default";
  // Pre-filter the Transactions page by the currently-selected month +
  // this row's category, so the "View X transactions" affordance lands
  // on the rows the user is actually looking at.
  const { start: monthStart, end: monthEnd } = boundsFor(month);
  const txLinkParams = new URLSearchParams({
    category_id: c.id,
    date_from: monthStart,
    date_to: monthEnd,
  });
  const txLink = `/transactions?${txLinkParams.toString()}`;
  return (
    <li className="transition-colors hover:bg-surface-soft">
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full min-h-[68px] items-center gap-md px-md py-3 text-left focus-ring"
      >
        <span
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full"
          style={{ backgroundColor: `color-mix(in srgb, ${c.color} 14%, transparent)` }}
        >
          <Wallet className="h-4 w-4" style={{ color: c.color }} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="font-medium text-text-primary">{c.name}</span>
            <span className="text-uppercase-label uppercase text-text-muted">
              {txCount} transaction{txCount === 1 ? "" : "s"}
            </span>
          </div>
          <Progress
            className="mt-1.5"
            // When budget is 0 and spent>0, `pct` is Infinity. Clamp to
            // 100% so the bar fills, and the tone+percentage label
            // below communicate the overshoot.
            value={Number.isFinite(pct) ? Math.min(100, pct) : 100}
            tone={tone as "default" | "warning" | "danger"}
          />
        </div>
        {/* Fixed `min-w-[200px]` so the spent/budget column doesn't shrink
            the bar's container by a different amount row-to-row — without
            this, varying number widths ("$50.78 / $34.78" vs
            "$938.11 / $231.9") squeeze the middle column unevenly and the
            progress bars come out at visibly different lengths even though
            they're all clamped to the same 100% value. */}
        <div className="shrink-0 min-w-[200px] text-right">
          <div className="text-body-small tabular">
            {formatMoney(spent, currency)}
            <span className="text-text-muted">
              {" "}
              / {formatMoney(c.monthly_budget, currency)}
            </span>
          </div>
          {/* Hide the % label entirely when budget=0 and spent>0 (pct is
              Infinity in that case). Rendering "—" left a small red
              underline-shaped artifact on Over-budget rows. The row's
              spent/budget figures + red progress bar already communicate
              the overshoot. */}
          {Number.isFinite(pct) && (
            <div
              className={cn(
                "text-uppercase-label uppercase tabular",
                bucket === "over" ? "text-danger" : bucket === "trending" ? "text-warning-700" : "text-text-muted",
              )}
            >
              {Math.round(pct)}%
            </div>
          )}
        </div>
        <ChevronDown
          className={cn(
            "h-4 w-4 text-text-muted transition-transform",
            expanded && "rotate-180",
          )}
        />
      </button>
      {expanded && (
        <div className="border-t border-border bg-surface-soft px-md py-3 text-body-small animate-slide-up">
          <p className="text-text-muted">
            Budget of <span className="font-medium text-text-primary">{formatMoney(c.monthly_budget, currency)}</span>{" "}
            per month. Spent <span className="font-medium text-text-primary">{formatMoney(spent, currency)}</span> so
            far
            {spent > 0 && (
              <>
                {" "}— {spent > c.monthly_budget ? "over by " : "remaining "}
                <span
                  className={cn(
                    "font-medium",
                    spent > c.monthly_budget ? "text-danger" : "text-success",
                  )}
                >
                  {formatMoney(Math.abs(c.monthly_budget - spent), currency)}
                </span>
              </>
            )}
            .
          </p>
          <p className="mt-1 text-uppercase-label uppercase text-text-muted">
            <Link to={txLink} className="hover:text-text-primary">
              View {c.name.toLowerCase()} transactions →
            </Link>
          </p>
        </div>
      )}
    </li>
  );
}

/** "Set budgets" side sheet — edits monthly_budget on every category at once. */
function SetBudgetsSheet({ trigger }: { trigger?: React.ReactNode }) {
  const qc = useQueryClient();
  const categoriesQuery = useQuery({
    queryKey: qk.categories.all(),
    queryFn: catApi.listCategories,
  });

  // Local draft of budgets; flushed to backend per-category on save.
  const [draft, setDraft] = useState<Record<string, number>>({});
  const [open, setOpen] = useState(false);

  const cats = categoriesQuery.data ?? [];

  const mutation = useMutation({
    mutationFn: async () => {
      const updates = cats
        .filter((c) => {
          const next = draft[c.id];
          return next !== undefined && next !== c.monthly_budget;
        })
        .map((c) =>
          catApi.updateCategory(c.id, { monthly_budget: draft[c.id]! }),
        );
      await Promise.all(updates);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.categories.all() });
      qc.invalidateQueries({ queryKey: qk.reports.all() });
      setOpen(false);
    },
  });

  // Initialize draft when sheet opens.
  const handleOpen = (o: boolean) => {
    setOpen(o);
    if (o && cats.length) {
      setDraft(Object.fromEntries(cats.map((c) => [c.id, c.monthly_budget])));
    }
  };

  return (
    <Sheet open={open} onOpenChange={handleOpen}>
      <SheetTrigger asChild>
        {trigger ?? (
          <Button variant="primary">
            <Pencil className="h-4 w-4" /> Set budgets
          </Button>
        )}
      </SheetTrigger>
      <SheetContent className="w-[480px] p-0">
        <SheetHeader>
          <SheetTitle>Set monthly budgets</SheetTitle>
          <p className="text-body-small text-text-muted">
            One value per category. Setting <strong>0</strong> means "no budget" and the row
            disappears from the Budget page until something is spent there.
          </p>
        </SheetHeader>
        <div className="max-h-[calc(100vh-220px)] overflow-y-auto px-lg pb-lg">
          {mutation.isError && (
            <div role="alert" className="mb-3 rounded-lg border border-danger/30 bg-danger/10 p-3 text-body-small text-danger">
              {parseApiError(mutation.error)}
            </div>
          )}
          <ul className="space-y-3">
            {cats.map((c) => (
              <li key={c.id} className="flex items-center justify-between gap-3">
                <span className="flex min-w-0 items-center gap-2 text-body-small font-medium">
                  <span
                    className="h-2.5 w-2.5 shrink-0 rounded-full"
                    style={{ backgroundColor: c.color }}
                  />
                  <span className="truncate">{c.name}</span>
                </span>
                <Input
                  type="number"
                  min={0}
                  step="0.01"
                  inputMode="decimal"
                  value={draft[c.id] ?? c.monthly_budget}
                  onChange={(e) =>
                    setDraft((d) => ({ ...d, [c.id]: Number(e.target.value) || 0 }))
                  }
                  className="w-32 text-right tabular"
                />
              </li>
            ))}
          </ul>
        </div>
        <SheetFooter className="border-t border-border">
          <Button variant="ghost" onClick={() => setOpen(false)} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button variant="primary" onClick={() => mutation.mutate()} disabled={mutation.isPending}>
            {mutation.isPending ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" /> Saving…
              </>
            ) : (
              "Save budgets"
            )}
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}
