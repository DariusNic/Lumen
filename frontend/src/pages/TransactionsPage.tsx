import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronLeft,
  ChevronRight,
  Loader2,
  MoreHorizontal,
  Plus,
  Search,
  Sparkles,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SectionCard } from "@/components/shared/SectionCard";
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
import { useCurrency } from "@/hooks/useCurrency";
import { qk } from "@/lib/queryKeys";
import { formatMoney } from "@/lib/format";
import { cn } from "@/lib/utils";
import * as catApi from "@/api/categories.api";
import * as txApi from "@/api/transactions.api";
import { TransactionFormDialog } from "@/components/transactions/TransactionFormDialog";
import { CsvImportDialog } from "@/components/transactions/CsvImportDialog";
import { parseApiError } from "@/api/client";

const PAGE_SIZE_OPTIONS = [25, 50, 100] as const;

export default function TransactionsPage() {
  const baseCurrency = useCurrency();
  const qc = useQueryClient();

  // Filter / pagination state — initialised from URL search params on
  // mount so deep-links (e.g. "/transactions?category_id=X&date_from=Y")
  // from other pages (Budget's "View X transactions") arrive pre-filtered.
  // After mount, the filters become normal client-side state — we don't
  // keep the URL in sync, so the user can edit filters freely without
  // history pollution.
  const [searchParams] = useSearchParams();
  const initialCategory = searchParams.get("category_id") ?? "";
  const initialDateFrom = searchParams.get("date_from") ?? "";
  const initialDateTo = searchParams.get("date_to") ?? "";

  const [search, setSearch] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [categoryFilter, setCategoryFilter] = useState<string>(initialCategory);
  const [dateFrom, setDateFrom] = useState<string>(initialDateFrom);
  const [dateTo, setDateTo] = useState<string>(initialDateTo);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState<(typeof PAGE_SIZE_OPTIONS)[number]>(50);

  // Dialogs
  const [addOpen, setAddOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [editing, setEditing] = useState<txApi.Transaction | null>(null);
  const [deleteCandidate, setDeleteCandidate] = useState<txApi.Transaction | null>(null);

  const params = useMemo(
    () => ({
      page,
      page_size: pageSize,
      search: search || undefined,
      category_id: categoryFilter || undefined,
      date_from: dateFrom ? new Date(`${dateFrom}T00:00:00`).toISOString() : undefined,
      date_to: dateTo ? new Date(`${dateTo}T23:59:59`).toISOString() : undefined,
    }),
    [page, pageSize, search, categoryFilter, dateFrom, dateTo],
  );

  const txQuery = useQuery({
    queryKey: qk.transactions.list(params),
    queryFn: () => txApi.listTransactions(params),
  });
  const categoriesQuery = useQuery({
    queryKey: qk.categories.all(),
    queryFn: catApi.listCategories,
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => txApi.deleteTransaction(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.transactions.all() });
      qc.invalidateQueries({ queryKey: qk.reports.all() });
      qc.invalidateQueries({ queryKey: qk.accounts.all() });
      setDeleteCandidate(null);
    },
  });

  const recatMutation = useMutation({
    mutationFn: (id: string) => txApi.recategorizeTransaction(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.transactions.all() });
      qc.invalidateQueries({ queryKey: qk.reports.all() });
    },
  });

  const setCategoryMutation = useMutation({
    mutationFn: (args: { id: string; categoryId: string }) =>
      txApi.updateTransaction(args.id, { category_id: args.categoryId }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.transactions.all() });
      qc.invalidateQueries({ queryKey: qk.reports.all() });
    },
  });

  const items = txQuery.data?.transactions ?? [];
  const total = txQuery.data?.total ?? 0;
  const lastPage = Math.max(1, Math.ceil(total / pageSize));

  const activeFiltersCount =
    (search ? 1 : 0) + (categoryFilter ? 1 : 0) + (dateFrom ? 1 : 0) + (dateTo ? 1 : 0);

  return (
    <div className="space-y-lg animate-fade-in">
      <header className="flex flex-wrap items-center justify-between gap-md">
        <div>
          <h1 className="text-h2 font-h2 text-text-primary">Transactions</h1>
          <p className="text-body-small text-text-muted">
            All money moving in and out of your accounts. {total > 0 && `${total} total.`}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="secondary" onClick={() => setImportOpen(true)}>
            <Upload className="h-4 w-4" /> Import CSV
          </Button>
          <Button
            variant="primary"
            onClick={() => {
              setEditing(null);
              setAddOpen(true);
            }}
          >
            <Plus className="h-4 w-4" /> Add transaction
          </Button>
        </div>
      </header>

      {/* Filter bar */}
      <SectionCard noPadding contentClassName="p-md">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            setPage(1);
            setSearch(searchInput.trim());
          }}
          className="flex flex-wrap items-center gap-2"
        >
          <div className="relative min-w-[240px] flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-muted" />
            <Input
              type="search"
              placeholder="Search by description or merchant"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              className="pl-10"
            />
          </div>
          <select
            value={categoryFilter}
            onChange={(e) => {
              setCategoryFilter(e.target.value);
              setPage(1);
            }}
            className="flex h-10 min-w-[160px] rounded-lg border border-border bg-surface px-3 text-body-small focus-ring"
          >
            <option value="">All categories</option>
            {(categoriesQuery.data ?? []).map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
          <Input
            type="date"
            value={dateFrom}
            onChange={(e) => {
              setDateFrom(e.target.value);
              setPage(1);
            }}
            className="w-[150px]"
            aria-label="From"
          />
          <Input
            type="date"
            value={dateTo}
            onChange={(e) => {
              setDateTo(e.target.value);
              setPage(1);
            }}
            className="w-[150px]"
            aria-label="To"
          />
          <Button variant="secondary" type="submit">
            Apply
          </Button>
          {activeFiltersCount > 0 && (
            <Button
              variant="ghost"
              type="button"
              onClick={() => {
                setSearch("");
                setSearchInput("");
                setCategoryFilter("");
                setDateFrom("");
                setDateTo("");
                setPage(1);
              }}
            >
              <X className="h-4 w-4" /> Clear ({activeFiltersCount})
            </Button>
          )}
        </form>
      </SectionCard>

      {/* Table */}
      <SectionCard noPadding>
        {txQuery.isLoading ? (
          <div className="flex items-center justify-center gap-2 py-2xl text-body-small text-text-muted">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading transactions…
          </div>
        ) : txQuery.isError ? (
          <div className="px-md py-lg text-body-small text-danger">
            {parseApiError(txQuery.error)}
          </div>
        ) : items.length === 0 ? (
          <div className="px-md py-2xl text-center">
            <p className="text-body font-medium text-text-primary">No transactions yet</p>
            <p className="mt-1 text-body-small text-text-muted">
              {activeFiltersCount > 0
                ? "Try clearing the filters above."
                : "Add a transaction manually or import a CSV from your bank to get started."}
            </p>
            {activeFiltersCount === 0 && (
              <div className="mt-md flex justify-center gap-2">
                <Button variant="secondary" onClick={() => setImportOpen(true)}>
                  <Upload className="h-4 w-4" /> Import CSV
                </Button>
                <Button
                  variant="primary"
                  onClick={() => {
                    setEditing(null);
                    setAddOpen(true);
                  }}
                >
                  <Plus className="h-4 w-4" /> Add transaction
                </Button>
              </div>
            )}
          </div>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-body-small">
                <thead>
                  <tr className="border-b border-border text-uppercase-label uppercase text-text-muted">
                    <th className="px-md py-3 text-left font-medium">Date</th>
                    <th className="px-md py-3 text-left font-medium">Description</th>
                    <th className="px-md py-3 text-left font-medium">Category</th>
                    <th className="px-md py-3 text-right font-medium">Amount</th>
                    <th className="w-10 px-md py-3"></th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((t) => (
                    <tr
                      key={t.id}
                      className="group border-b border-border/60 transition-colors hover:bg-surface-soft last:border-0"
                    >
                      <td className="px-md py-3 text-text-muted whitespace-nowrap">
                        {new Date(t.date).toLocaleDateString("en-US", {
                          month: "short",
                          day: "numeric",
                          year:
                            new Date(t.date).getFullYear() !== new Date().getFullYear()
                              ? "numeric"
                              : undefined,
                        })}
                      </td>
                      <td className="px-md py-3">
                        <div className="font-medium text-text-primary">{t.description}</div>
                        {t.merchant && (
                          <div className="text-uppercase-label uppercase text-text-muted">
                            {t.merchant}
                          </div>
                        )}
                      </td>
                      <td className="px-md py-3">
                        <CategoryPill
                          category={
                            categoriesQuery.data?.find((c) => c.id === t.category_id) ?? null
                          }
                          tx={t}
                          allCategories={categoriesQuery.data ?? []}
                          onChange={(catId) =>
                            setCategoryMutation.mutate({ id: t.id, categoryId: catId })
                          }
                          isPending={
                            setCategoryMutation.isPending && setCategoryMutation.variables?.id === t.id
                          }
                        />
                      </td>
                      <td
                        className={cn(
                          "px-md py-3 text-right tabular whitespace-nowrap",
                          t.amount > 0 ? "text-success" : "text-text-primary",
                        )}
                      >
                        <div className="font-semibold">
                          {t.amount_base > 0 ? "+" : ""}
                          {formatMoney(t.amount_base, baseCurrency)}
                        </div>
                        {t.currency !== baseCurrency && (
                          <div className="text-uppercase-label text-text-muted normal-case">
                            ≈ {t.amount > 0 ? "+" : ""}
                            {formatMoney(t.amount, t.currency)}
                          </div>
                        )}
                      </td>
                      <td className="px-md py-3">
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button
                              variant="ghost"
                              size="icon-sm"
                              aria-label="Row actions"
                              className="text-text-muted hover:text-text-primary"
                            >
                              <MoreHorizontal className="h-4 w-4" />
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            {t.source === "goal_contribution" ? (
                              // Goal contributions are managed by `goal.saved_amount`
                              // which lives outside the transactions collection.
                              // Editing or deleting the tx in isolation would
                              // desync the goal; route the user to the Goals page
                              // for any change.
                              <DropdownMenuItem disabled>
                                Managed from the Goals page
                              </DropdownMenuItem>
                            ) : t.source === "recurring" ? (
                              // Planned-payment-sourced transactions: edit OK
                              // (actual paid amount can differ from the template
                              // — corrected bill, partial payment, etc), but
                              // delete is blocked. The recurring's `next_due`
                              // already rolled forward when the tx was created,
                              // so a unilateral delete here would leave the
                              // Planned page silently marked "paid" with no
                              // matching row in the ledger. Re-run via the
                              // Planned page if you need to undo a cycle.
                              <>
                                <DropdownMenuItem
                                  onSelect={() => {
                                    setEditing(t);
                                    setAddOpen(true);
                                  }}
                                >
                                  Edit
                                </DropdownMenuItem>
                                <DropdownMenuItem onSelect={() => recatMutation.mutate(t.id)}>
                                  <Sparkles className="h-3.5 w-3.5" /> Re-run categorizer
                                </DropdownMenuItem>
                                <DropdownMenuSeparator />
                                <DropdownMenuItem disabled>
                                  Delete managed from the Planned page
                                </DropdownMenuItem>
                              </>
                            ) : (
                              <>
                                <DropdownMenuItem
                                  onSelect={() => {
                                    setEditing(t);
                                    setAddOpen(true);
                                  }}
                                >
                                  Edit
                                </DropdownMenuItem>
                                <DropdownMenuItem onSelect={() => recatMutation.mutate(t.id)}>
                                  <Sparkles className="h-3.5 w-3.5" /> Re-run categorizer
                                </DropdownMenuItem>
                                <DropdownMenuSeparator />
                                <DropdownMenuItem
                                  onSelect={() => setDeleteCandidate(t)}
                                  className="text-danger focus:bg-danger/10 focus:text-danger"
                                >
                                  <Trash2 className="h-3.5 w-3.5" /> Delete
                                </DropdownMenuItem>
                              </>
                            )}
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-md py-3 text-body-small">
              <div className="flex items-center gap-2 text-text-muted">
                <span>Rows per page</span>
                <select
                  value={pageSize}
                  onChange={(e) => {
                    setPageSize(Number(e.target.value) as (typeof PAGE_SIZE_OPTIONS)[number]);
                    setPage(1);
                  }}
                  className="rounded-md border border-border bg-surface px-2 py-1 focus-ring"
                >
                  {PAGE_SIZE_OPTIONS.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
              </div>
              <div className="text-text-muted">
                Showing {(page - 1) * pageSize + 1}–{Math.min(page * pageSize, total)} of {total}
              </div>
              <div className="flex items-center gap-1">
                <Button
                  variant="ghost"
                  size="icon-sm"
                  disabled={page <= 1}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  aria-label="Previous page"
                >
                  <ChevronLeft className="h-4 w-4" />
                </Button>
                <span className="px-2 tabular">
                  {page} / {lastPage}
                </span>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  disabled={page >= lastPage}
                  onClick={() => setPage((p) => Math.min(lastPage, p + 1))}
                  aria-label="Next page"
                >
                  <ChevronRight className="h-4 w-4" />
                </Button>
              </div>
            </footer>
          </>
        )}
      </SectionCard>

      {baseCurrency && null /* keep import */}

      <TransactionFormDialog
        open={addOpen}
        onOpenChange={(o) => {
          setAddOpen(o);
          if (!o) setEditing(null);
        }}
        editing={editing}
      />
      <CsvImportDialog open={importOpen} onOpenChange={setImportOpen} />
      <ConfirmDeleteDialog
        candidate={deleteCandidate}
        onClose={() => setDeleteCandidate(null)}
        onConfirm={(id) => deleteMutation.mutate(id)}
        isPending={deleteMutation.isPending}
      />
    </div>
  );
}

/* ---------- Category pill (click to recategorize) ---------- */

function CategoryPill({
  category,
  tx,
  allCategories,
  onChange,
  isPending,
}: {
  category: catApi.Category | null;
  tx: txApi.Transaction;
  allCategories: catApi.Category[];
  onChange: (categoryId: string) => void;
  isPending: boolean;
}) {
  const color = category?.color ?? "#94a3b8";
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          aria-label={`Change category for ${tx.description}`}
          className="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-uppercase-label uppercase transition-all focus-ring hover:ring-2 hover:ring-primary/30"
          style={{
            backgroundColor: `color-mix(in srgb, ${color} 14%, transparent)`,
            color,
          }}
          disabled={isPending}
        >
          <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: color }} />
          {isPending ? "…" : category?.name ?? tx.category_name ?? "Uncategorized"}
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="max-h-[320px] overflow-y-auto">
        {allCategories.map((c) => (
          <DropdownMenuItem
            key={c.id}
            onSelect={() => onChange(c.id)}
            className="justify-between"
          >
            <span className="flex items-center gap-2">
              <span className="h-2 w-2 rounded-full" style={{ backgroundColor: c.color }} />
              {c.name}
            </span>
            {c.id === tx.category_id && (
              <span className="text-uppercase-label text-primary">Active</span>
            )}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/* ---------- Confirm delete ---------- */

function ConfirmDeleteDialog({
  candidate,
  onClose,
  onConfirm,
  isPending,
}: {
  candidate: txApi.Transaction | null;
  onClose: () => void;
  onConfirm: (id: string) => void;
  isPending: boolean;
}) {
  return (
    <Dialog open={!!candidate} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Delete transaction?</DialogTitle>
          <DialogDescription>
            The transaction will be removed from your reports immediately. This cannot be undone.
          </DialogDescription>
        </DialogHeader>
        {candidate && (
          <div className="rounded-lg border border-border bg-surface-soft p-3 text-body-small">
            <div className="font-medium text-text-primary">{candidate.description}</div>
            <div className="text-text-muted tabular">
              {new Date(candidate.date).toLocaleDateString()} ·{" "}
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
