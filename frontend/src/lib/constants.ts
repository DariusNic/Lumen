export const SUPPORTED_CURRENCIES = ["RON", "EUR", "USD"] as const;
export type Currency = (typeof SUPPORTED_CURRENCIES)[number];

export const DEFAULT_BASE_CURRENCY: Currency = "RON";

export const CATEGORIES = [
  "Groceries",
  "Restaurants",
  "Transport",
  "Housing",
  "Utilities",
  "Health",
  "Entertainment",
  "Subscriptions",
  "Education",
  "Travel",
  "Salary",
  "Transfer",
  "Investments",
  "Other",
] as const;

export type Category = (typeof CATEGORIES)[number];
