import { apiClient } from "./client";

export type SearchKind =
  | "transaction"
  | "goal"
  | "category"
  | "recurring"
  | "account"
  | "stock";

export interface SearchResult {
  kind: SearchKind;
  id: string;
  title: string;
  subtitle: string;
  link: string;
  score: number;
}

export interface SearchResponse {
  query: string;
  results: SearchResult[];
}

export async function search(query: string, limit = 20): Promise<SearchResponse> {
  if (!query.trim()) {
    return { query: "", results: [] };
  }
  const res = await apiClient.get<SearchResponse>("/search", {
    params: { q: query, limit },
  });
  return res.data;
}
