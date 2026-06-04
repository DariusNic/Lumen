from datetime import datetime
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.user import Currency

# "once" = one-off planned payment (wedding, tax bill, planned trip).
# All others = recurring patterns. Detection only ever produces non-"once" frequencies.
Frequency = Literal["once", "weekly", "biweekly", "monthly", "yearly"]
RecurringStatus = Literal["active", "paused", "completed"]
Amount = Annotated[float, Field(gt=0, allow_inf_nan=False)]


class RecurringCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    merchant_pattern: str = Field(min_length=1, max_length=200)
    amount: Amount
    currency: Currency
    frequency: Frequency
    start_date: datetime
    end_date: Optional[datetime] = None
    category_id: Optional[str] = None
    is_income: bool = False
    auto_create_transaction: Optional[bool] = None  # None → service applies sensible default per kind


class RecurringUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    merchant_pattern: Optional[str] = Field(default=None, min_length=1, max_length=200)
    amount: Optional[Amount] = None
    currency: Optional[Currency] = None
    frequency: Optional[Frequency] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    category_id: Optional[str] = None
    is_income: Optional[bool] = None
    auto_create_transaction: Optional[bool] = None
    status: Optional[RecurringStatus] = None


class RecurringPublic(BaseModel):
    id: str
    name: str
    merchant_pattern: str
    amount: float
    # `amount` in the user's base currency, computed on read using today's FX
    # rate. None if FX is unavailable (frontend falls back to `amount`).
    amount_base: Optional[float] = None
    currency: Currency
    frequency: Frequency
    start_date: datetime
    end_date: Optional[datetime]
    category_id: Optional[str]
    category_name: Optional[str] = None
    # Optional back-reference to a goal. When set, materialization in
    # `recurring_service.materialize_due` routes through
    # `goal_service.contribute` instead of the regular tx_service path —
    # so the contribution increments saved_amount AND creates a goal
    # transaction in one atomic logical step.
    goal_id: Optional[str] = None
    is_income: bool
    auto_create_transaction: bool
    status: RecurringStatus
    next_due: datetime
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# Detection only ever produces *recurring* (≥2 occurrences) patterns, so its
# Frequency space excludes "once". Keeping this as a separate type guards the
# detector against accidentally suggesting one-off planned payments.
DetectedFrequency = Literal["weekly", "biweekly", "monthly", "yearly"]


class DetectionSuggestion(BaseModel):
    """A suggested recurring pattern, returned by the detection function.

    The user confirms (creates a real RecurringPublic) or dismisses each one;
    nothing is auto-promoted.
    """

    merchant_pattern: str
    average_amount: float
    currency: Currency
    frequency: DetectedFrequency
    occurrences: int
    last_seen: datetime
    is_income: bool
    sample_descriptions: list[str]


class DetectionResult(BaseModel):
    suggestions: list[DetectionSuggestion]
    transactions_scanned: int
    clusters_found: int
