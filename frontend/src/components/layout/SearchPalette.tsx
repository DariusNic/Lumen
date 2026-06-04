import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Building2,
  ListTree,
  Loader2,
  Receipt,
  Repeat,
  Search,
  Target,
  TrendingUp,
  type LucideIcon,
} from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { search, type SearchKind, type SearchResult } from "@/api/search.api";
import { qk } from "@/lib/queryKeys";
import { cn } from "@/lib/utils";

interface SearchPaletteProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const KIND_ICON: Record<SearchKind, LucideIcon> = {
  transaction: Receipt,
  goal: Target,
  category: ListTree,
  recurring: Repeat,
  account: Building2,
  stock: TrendingUp,
};

const KIND_LABEL: Record<SearchKind, string> = {
  transaction: "Transactions",
  goal: "Goals",
  category: "Categories",
  recurring: "Planned",
  account: "Accounts",
  stock: "Stocks",
};

const KIND_ORDER: SearchKind[] = [
  "stock",
  "goal",
  "category",
  "account",
  "recurring",
  "transaction",
];

function useDebounced<T>(value: T, delay = 200): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}

export function SearchPalette({ open, onOpenChange }: SearchPaletteProps) {
  const [query, setQuery] = useState("");
  const debounced = useDebounced(query, 180);
  const navigate = useNavigate();

  // Reset on close
  useEffect(() => {
    if (!open) setQuery("");
  }, [open]);

  const { data, isFetching } = useQuery({
    queryKey: qk.search.query(debounced),
    queryFn: () => search(debounced, 20),
    enabled: open && debounced.trim().length > 0,
    staleTime: 30_000,
  });

  const results = data?.results ?? [];
  const grouped = KIND_ORDER.map((kind) => ({
    kind,
    items: results.filter((r) => r.kind === kind),
  })).filter((g) => g.items.length > 0);

  const onSelect = (r: SearchResult) => {
    onOpenChange(false);
    navigate(r.link);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl gap-0 p-0 overflow-hidden">
        <DialogTitle className="sr-only">Search</DialogTitle>
        <DialogDescription className="sr-only">
          Find transactions, goals, stocks, and more.
        </DialogDescription>
        <div className="flex items-center gap-3 border-b border-border px-md py-3">
          <Search className="h-4 w-4 shrink-0 text-text-muted" />
          <Input
            autoFocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search transactions, stocks, goals…"
            className="border-0 bg-transparent p-0 text-body shadow-none focus-visible:ring-0"
          />
          {isFetching && (
            <Loader2 className="h-4 w-4 shrink-0 animate-spin text-text-muted" />
          )}
        </div>
        <div className="max-h-[420px] overflow-y-auto p-2">
          {!query.trim() ? (
            <Hint message="Start typing to search across your data." />
          ) : !isFetching && results.length === 0 ? (
            <Hint message={`No results for "${query}".`} />
          ) : (
            grouped.map((g) => {
              const Icon = KIND_ICON[g.kind];
              return (
                <div key={g.kind} className="mb-2 last:mb-0">
                  <div className="px-2 pb-1 text-uppercase-label uppercase text-text-muted">
                    {KIND_LABEL[g.kind]}
                  </div>
                  <ul className="space-y-0.5">
                    {g.items.map((r) => (
                      <li key={`${r.kind}-${r.id}`}>
                        <button
                          type="button"
                          onClick={() => onSelect(r)}
                          className={cn(
                            "flex w-full items-start gap-3 rounded-md px-2 py-2 text-left",
                            "transition-colors hover:bg-surface-soft focus-ring",
                          )}
                        >
                          <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-surface-soft text-primary">
                            <Icon className="h-4 w-4" />
                          </span>
                          <span className="min-w-0 flex-1">
                            <span className="block truncate text-body-small font-medium text-text-primary">
                              {r.title}
                            </span>
                            <span className="block truncate text-uppercase-label uppercase text-text-muted">
                              {r.subtitle}
                            </span>
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              );
            })
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

function Hint({ message }: { message: string }) {
  return (
    <div className="px-md py-lg text-center text-body-small text-text-muted">
      {message}
    </div>
  );
}
