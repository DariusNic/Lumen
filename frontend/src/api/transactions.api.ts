import { apiClient } from "./client";
import type { Currency } from "@/lib/constants";

export type TxSource = "manual" | "csv" | "import" | "recurring" | "goal_contribution";

export interface Transaction {
  id: string;
  date: string;
  amount: number;
  amount_base: number;
  currency: Currency;
  description: string;
  merchant: string | null;
  category_id: string | null;
  category_name: string | null;
  account_id: string | null;
  source: TxSource;
  is_recurring: boolean;
  created_at: string;
}

export interface TransactionListResponse {
  transactions: Transaction[];
  total: number;
  page: number;
  page_size: number;
}

export interface TransactionListParams {
  page?: number;
  page_size?: number;
  date_from?: string;
  date_to?: string;
  category_id?: string;
  search?: string;
}

export interface TransactionCreatePayload {
  date: string;
  amount: number;
  currency: Currency;
  description: string;
  merchant?: string | null;
  category_id?: string | null;
  account_id?: string | null;
  source?: TxSource;
}

export interface TransactionUpdatePayload {
  date?: string;
  amount?: number;
  currency?: Currency;
  description?: string;
  merchant?: string | null;
  category_id?: string | null;
}

export async function listTransactions(
  params: TransactionListParams = {},
): Promise<TransactionListResponse> {
  const res = await apiClient.get<TransactionListResponse>("/transactions", { params });
  return res.data;
}

export async function getTransaction(id: string): Promise<Transaction> {
  const res = await apiClient.get<{ transaction: Transaction }>(`/transactions/${id}`);
  return res.data.transaction;
}

export async function createTransaction(
  payload: TransactionCreatePayload,
): Promise<Transaction> {
  const res = await apiClient.post<{ transaction: Transaction }>("/transactions", payload);
  return res.data.transaction;
}

export async function updateTransaction(
  id: string,
  payload: TransactionUpdatePayload,
): Promise<Transaction> {
  const res = await apiClient.patch<{ transaction: Transaction }>(
    `/transactions/${id}`,
    payload,
  );
  return res.data.transaction;
}

export async function deleteTransaction(id: string): Promise<void> {
  await apiClient.delete(`/transactions/${id}`);
}

export async function recategorizeTransaction(id: string): Promise<Transaction> {
  const res = await apiClient.post<{ transaction: Transaction }>(
    `/transactions/${id}/categorize`,
  );
  return res.data.transaction;
}

// ---------- CSV import ----------

export interface ImportPreviewResult {
  headers: string[];
  sample_rows: Record<string, string>[];
  suggested_mapping: {
    date: string | null;
    description: string | null;
    merchant: string | null;
    amount: string | null;
    debit: string | null;
    credit: string | null;
    currency: string | null;
  };
  delimiter: string;
  total_rows: number;
}

export interface ImportMapping {
  date: string;
  description: string;
  amount?: string;
  debit?: string;
  credit?: string;
  currency?: string;
  merchant?: string;
  default_currency: Currency;
}

export interface ImportCommitResult {
  inserted: number;
  skipped: number;
  errors: string[];
}

export async function previewCsv(file: File): Promise<ImportPreviewResult> {
  const fd = new FormData();
  fd.append("file", file);
  const res = await apiClient.post<ImportPreviewResult>(
    "/transactions/import/preview",
    fd,
    { headers: { "Content-Type": "multipart/form-data" } },
  );
  return res.data;
}

export async function commitCsvImport(
  file: File,
  mapping: ImportMapping,
): Promise<ImportCommitResult> {
  const fd = new FormData();
  fd.append("file", file);
  fd.append("mapping", JSON.stringify(mapping));
  const res = await apiClient.post<ImportCommitResult>(
    "/transactions/import/commit",
    fd,
    { headers: { "Content-Type": "multipart/form-data" } },
  );
  return res.data;
}
