from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# 14 system categories. Auto-seeded on user signup.
# Color maps to a Tailwind 500/600/700 hex so the frontend can render directly.
DEFAULT_CATEGORIES: list[dict[str, str]] = [
    {"name": "Groceries",     "color": "#10b981"},  # emerald-500
    {"name": "Restaurants",   "color": "#4f46e5"},  # indigo-600
    {"name": "Transport",     "color": "#06b6d4"},  # cyan-500
    {"name": "Housing",       "color": "#f43f5e"},  # rose-500
    {"name": "Utilities",     "color": "#14b8a6"},  # teal-500
    {"name": "Health",        "color": "#ec4899"},  # pink-500
    {"name": "Entertainment", "color": "#8b5cf6"},  # violet-500
    {"name": "Subscriptions", "color": "#f59e0b"},  # amber-500
    {"name": "Education",     "color": "#0ea5e9"},  # sky-500
    {"name": "Travel",        "color": "#f97316"},  # orange-500
    {"name": "Salary",        "color": "#16a34a"},  # green-600 (income)
    {"name": "Transfer",      "color": "#64748b"},  # slate-500
    {"name": "Investments",   "color": "#4338ca"},  # indigo-700
    {"name": "Goals",         "color": "#a855f7"},  # purple-500 (savings goals)
    {"name": "Other",         "color": "#94a3b8"},  # slate-400 (fallback)
]


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    monthly_budget: float = Field(default=0.0, ge=0)


class CategoryUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=60)
    color: Optional[str] = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    monthly_budget: Optional[float] = Field(default=None, ge=0)


class CategoryPublic(BaseModel):
    id: str
    name: str
    color: str
    monthly_budget: float
    is_default: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
