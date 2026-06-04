import { apiClient } from "./client";

export interface Category {
  id: string;
  name: string;
  color: string;
  monthly_budget: number;
  is_default: boolean;
  created_at: string;
}

export interface CategoryCreatePayload {
  name: string;
  color: string;
  monthly_budget?: number;
}

export interface CategoryUpdatePayload {
  name?: string;
  color?: string;
  monthly_budget?: number;
}

export async function listCategories(): Promise<Category[]> {
  const res = await apiClient.get<{ categories: Category[] }>("/categories");
  return res.data.categories;
}

export async function createCategory(payload: CategoryCreatePayload): Promise<Category> {
  const res = await apiClient.post<{ category: Category }>("/categories", payload);
  return res.data.category;
}

export async function updateCategory(
  id: string,
  payload: CategoryUpdatePayload,
): Promise<Category> {
  const res = await apiClient.patch<{ category: Category }>(`/categories/${id}`, payload);
  return res.data.category;
}

export async function deleteCategory(id: string): Promise<void> {
  await apiClient.delete(`/categories/${id}`);
}
