from datetime import datetime
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.user import Currency, to_utc_naive, utcnow

TxSource = Literal["manual", "csv", "import", "recurring", "goal_contribution"]
Amount = Annotated[float, Field(allow_inf_nan=False)]


def _reject_future(v: datetime) -> datetime:
    """Reject transaction dates strictly in the future. Defense-in-depth —
    the form already constrains via `max=today`, but the API is the boundary
    that has to enforce the rule (CSV imports go through here too)."""
    naive = to_utc_naive(v)
    if naive > utcnow():
        raise ValueError("Transaction date can't be in the future")
    return v


class TransactionCreate(BaseModel):
    """Inbound payload for creating a single transaction.

    `amount` is signed: negative = expense, positive = income.
    `category_id` is optional; the service auto-categorizes from `description`
    when omitted.
    `account_id` is optional for week 2 (Accounts CRUD lands later).
    """

    date: datetime
    amount: Amount
    currency: Currency
    description: str = Field(min_length=1, max_length=400)
    merchant: Optional[str] = Field(default=None, max_length=200)
    category_id: Optional[str] = None
    account_id: Optional[str] = None
    source: TxSource = "manual"

    @field_validator("date")
    @classmethod
    def _date_not_future(cls, v: datetime) -> datetime:
        return _reject_future(v)


class TransactionUpdate(BaseModel):
    date: Optional[datetime] = None
    amount: Optional[Amount] = None
    currency: Optional[Currency] = None
    description: Optional[str] = Field(default=None, min_length=1, max_length=400)
    merchant: Optional[str] = Field(default=None, max_length=200)
    category_id: Optional[str] = None

    @field_validator("date")
    @classmethod
    def _date_not_future(cls, v: Optional[datetime]) -> Optional[datetime]:
        return _reject_future(v) if v is not None else v


class TransactionPublic(BaseModel):
    id: str
    date: datetime
    amount: float
    amount_base: float
    currency: Currency
    description: str
    merchant: Optional[str]
    category_id: Optional[str]
    category_name: Optional[str] = None  # resolved on read for UI convenience
    account_id: Optional[str]
    source: TxSource
    is_recurring: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TransactionListQuery(BaseModel):
    """Filter/pagination params for GET /api/transactions."""

    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    category_id: Optional[str] = None
    search: Optional[str] = Field(default=None, max_length=200)
    page: int = Field(default=1, ge=1, le=10_000)
    page_size: int = Field(default=50, ge=1, le=200)
