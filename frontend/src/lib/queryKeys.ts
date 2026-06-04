/**
 * Single source of truth for TanStack Query keys.
 * Every query/mutation in the app reads keys from here so invalidation stays
 * consistent. Adding a new resource? Add a `qk.<resource>` block.
 */
export const qk = {
  me: () => ["me"] as const,

  categories: {
    all: () => ["categories"] as const,
  },

  transactions: {
    all: () => ["transactions"] as const,
    list: (params: Record<string, unknown>) => ["transactions", "list", params] as const,
    detail: (id: string) => ["transactions", "detail", id] as const,
  },

  accounts: {
    all: () => ["accounts"] as const,
  },

  goals: {
    all: () => ["goals"] as const,
    detail: (id: string) => ["goals", "detail", id] as const,
  },

  recurring: {
    all: () => ["recurring"] as const,
    calendar: (year: number, month: number) =>
      ["recurring", "calendar", year, month] as const,
  },

  reports: {
    all: () => ["reports"] as const,
    spending: (from?: string, to?: string) =>
      ["reports", "spending", from, to] as const,
    monthly: (months: number, end?: string) =>
      ["reports", "monthly", months, end ?? null] as const,
    merchants: (from?: string, to?: string, limit?: number) =>
      ["reports", "merchants", from, to, limit] as const,
  },

  alerts: {
    all: () => ["alerts"] as const,
    list: () => ["alerts", "list"] as const,
  },

  search: {
    all: () => ["search"] as const,
    query: (q: string) => ["search", "query", q] as const,
  },

  networth: {
    all: () => ["networth"] as const,
    current: () => ["networth", "current"] as const,
    history: (range: string) => ["networth", "history", range] as const,
  },

  stocks: {
    all: () => ["stocks"] as const,
    list: () => ["stocks", "list"] as const,
    detail: (ticker: string, range: string) => ["stocks", "detail", ticker, range] as const,
    signal: (ticker: string) => ["stocks", "signal", ticker] as const,
    signalsBatch: () => ["stocks", "signals"] as const,
  },

  portfolio: {
    all: () => ["portfolio"] as const,
    current: () => ["portfolio", "current"] as const,
    history: (range: string) => ["portfolio", "history", range] as const,
    trades: () => ["portfolio", "trades"] as const,
  },

  fx: {
    all: () => ["fx"] as const,
    rate: (from: string, to: string) => ["fx", "rate", from, to] as const,
  },
} as const;
