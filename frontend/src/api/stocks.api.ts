import { apiClient } from "./client";

export type SignalLabel = "BUY" | "HOLD" | "SELL";
export type StockRange = "1M" | "3M" | "6M" | "1Y" | "ALL";

export interface TickerSummary {
  ticker: string;
  name: string;
  sector: string;
  last_close: number;
  last_date: string;
  change_1d_pct: number | null;
  change_5d_pct: number | null;
}

export interface StocksListResponse {
  tickers: TickerSummary[];
  total: number;
}

export interface SignalsBatchResponse {
  signals: SignalResponse[];
  total: number;
}

export interface OHLCVBar {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface TickerHistoryResponse {
  ticker: string;
  name: string;
  sector: string;
  range: StockRange;
  rows: number;
  history: OHLCVBar[];
}

export interface SignalResponse {
  ticker: string;
  as_of: string;
  label: SignalLabel;
  confidence: number;
  probabilities: Record<SignalLabel, number>;
  explanation: string;
}

export async function listStocks(): Promise<StocksListResponse> {
  const res = await apiClient.get<StocksListResponse>("/stocks");
  return res.data;
}

export async function getTicker(ticker: string, range: StockRange = "3M"): Promise<TickerHistoryResponse> {
  const res = await apiClient.get<TickerHistoryResponse>(`/stocks/${ticker}`, {
    params: { range },
  });
  return res.data;
}

export async function getSignal(ticker: string): Promise<SignalResponse> {
  const res = await apiClient.get<SignalResponse>(`/stocks/${ticker}/signal`);
  return res.data;
}

export async function getAllSignals(): Promise<SignalsBatchResponse> {
  const res = await apiClient.get<SignalsBatchResponse>("/stocks/signals");
  return res.data;
}
