from datetime import datetime
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

from app.models.user import Currency

GoalType = Literal["travel", "home", "emergency", "education", "vehicle", "other"]
Amount = Annotated[float, Field(ge=0, allow_inf_nan=False)]


class AutoContributeSetup(BaseModel):
    """Optional auto-contribute schedule attached to a goal. When present
    on create/update, the service writes a `recurring_payments` row with
    `goal_id` pointing back to the goal — that row drives the cron and
    surfaces on the Planned page like any other recurring payment."""
    amount: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    # First firing date. Subsequent firings are computed by the recurring
    # service's monthly cadence. The day-of-month part of this timestamp
    # is what the user expects to see in the calendar.
    start_date: datetime


class GoalCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    target_amount: Amount
    currency: Currency
    target_date: datetime
    type: GoalType = "other"
    priority: int = Field(default=3, ge=1, le=5)
    initial_deposit: Amount = 0.0
    auto_contribute: Optional[AutoContributeSetup] = None


class GoalUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=80)
    target_amount: Optional[Amount] = None
    target_date: Optional[datetime] = None
    type: Optional[GoalType] = None
    priority: Optional[int] = Field(default=None, ge=1, le=5)
    # Tri-state auto-contribute control:
    #   - None  → field omitted, no change to the linked recurring
    #   - {...} → upsert: create one if missing, otherwise update amount/day
    #   - False → disable: soft-delete the linked recurring
    # Anchor the union on AutoContributeSetup so Pydantic doesn't coerce
    # `False` into an empty object via lax mode.
    auto_contribute: Optional[Union[AutoContributeSetup, Literal[False]]] = None


class GoalContribute(BaseModel):
    amount: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    when: Optional[datetime] = None


class AutoContributeInfo(BaseModel):
    """Read-side view of the linked recurring's schedule. Populated by
    looking up `recurring_payments where goal_id=<this> AND status=active`."""
    amount: float
    next_due: datetime
    recurring_id: str


class GoalPublic(BaseModel):
    id: str
    name: str
    target_amount: float
    saved_amount: float
    currency: Currency
    target_date: datetime
    type: GoalType
    priority: int
    progress_pct: float
    monthly_simple: float
    months_remaining: int
    status: Literal["on-track", "behind", "ahead", "completed"]
    # Present when the goal has an active recurring auto-contribute row.
    # Null otherwise — UI uses this to decide whether to show the
    # "Auto · €X/mo" chip on the goal card.
    auto_contribute: Optional[AutoContributeInfo] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
