import { apiClient } from "./client";

export type TradeSide = "buy" | "sell" | "deposit" | "withdrawal";
export type FundsDirection = "deposit" | "withdrawal";
export type PortfolioRange = "1M" | "3M" | "6M" | "1Y" | "ALL";

export interface Holding {
  ticker: string;
  qty: number;
  avg_cost: number;
  last_price: number | null;
  market_value: number | null;
  unrealized_pnl: number | null;
  unrealized_pnl_pct: number | null;
}

export interface Portfolio {
  cash_usd: number;
  initial_cash_usd: number;
  holdings: Holding[];
  market_value_usd: number;
  total_value_usd: number;
  cost_basis_usd: number;
  unrealized_pnl_usd: number;
  unrealized_pnl_pct: number;
  total_return_usd: number;
  total_return_pct: number;
  trade_count: number;
  created_at: string;
  reset_at: string | null;
}

export interface Trade {
  id: string;
  date: string;
  ticker: string;
  side: TradeSide;
  qty: number;
  price: number;
  total: number;
  realized_pnl: number | null;
}

export interface TradesListResponse {
  trades: Trade[];
}

export interface EquityPoint {
  date: string;
  cash_usd: number;
  market_value_usd: number;
  total_value_usd: number;
}

export interface PortfolioHistoryResponse {
  range: PortfolioRange;
  points: EquityPoint[];
  initial_cash_usd: number;
}

export async function getPortfolio(): Promise<Portfolio> {
  const res = await apiClient.get<Portfolio>("/portfolio");
  return res.data;
}

export async function getHistory(range: PortfolioRange = "3M"): Promise<PortfolioHistoryResponse> {
  const res = await apiClient.get<PortfolioHistoryResponse>("/portfolio/history", {
    params: { range },
  });
  return res.data;
}

export async function listTrades(limit = 200): Promise<Trade[]> {
  const res = await apiClient.get<TradesListResponse>("/portfolio/trades", {
    params: { limit },
  });
  return res.data.trades;
}

export async function buy(ticker: string, qty: number): Promise<Trade> {
  const res = await apiClient.post<{ trade: Trade }>("/portfolio/buy", { ticker, qty });
  return res.data.trade;
}

export async function sell(ticker: string, qty: number): Promise<Trade> {
  const res = await apiClient.post<{ trade: Trade }>("/portfolio/sell", { ticker, qty });
  return res.data.trade;
}

export async function reset(): Promise<Portfolio> {
  const res = await apiClient.post<Portfolio>("/portfolio/reset");
  return res.data;
}

export async function adjustFunds(
  direction: FundsDirection,
  amount_usd: number,
): Promise<Trade> {
  const res = await apiClient.post<{ trade: Trade }>("/portfolio/funds", {
    direction,
    amount_usd,
  });
  return res.data.trade;
}
