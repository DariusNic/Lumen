from datetime import datetime, timezone
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
Email = Annotated[str, Field(pattern=EMAIL_PATTERN, max_length=255)]
Currency = Literal["RON", "EUR", "USD"]


def _default_now_source() -> datetime:
    """Wall-clock source. Indirected so the test harness can freeze it.
    See `_set_now_source` for the override hook."""
    return datetime.now(timezone.utc)


# Module-level indirection point. `utcnow()` resolves this name on every
# call, so swapping it via `_set_now_source` propagates to every module
# that imported `utcnow` — including those that did `from app.models.user
# import utcnow` (Python's late-binding inside the function body looks up
# `_now_source` in this module's globals at call time).
_now_source = _default_now_source


def utcnow() -> datetime:
    """All timestamps are UTC.

    Returned as **naive UTC** to match PyMongo's default storage representation
    (`tz_aware=False`). Mixing aware + naive datetimes in queries fails silently
    on Python comparisons, so we normalize at the boundary.

    For deterministic time-based tests, use the `freeze_time` fixture in
    `tests/conftest.py` — it swaps `_now_source` to a controllable callable.
    """
    return _now_source().replace(tzinfo=None)


def _set_now_source(source) -> None:
    """Test-only hook. Replace with a callable returning a `datetime` (any
    tz, will be normalized to naive UTC by `utcnow`). Pass `None` to restore
    the default wall-clock source."""
    global _now_source
    _now_source = source if source is not None else _default_now_source


def to_utc_naive(dt: datetime) -> datetime:
    """Normalize any datetime to naive UTC. Used on every datetime that flows
    into Mongo (insert, filter, range query). Naive inputs are assumed to be
    UTC already (matches Pydantic's default ISO-8601 parsing behavior)."""
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


class UserCreate(BaseModel):
    email: Email
    password: str = Field(min_length=8, max_length=200)
    full_name: str = Field(min_length=1, max_length=120)
    base_currency: Currency = "RON"


class UserUpdate(BaseModel):
    full_name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    base_currency: Optional[Currency] = None


class UserPublic(BaseModel):
    """Shape returned to the client. Never includes the password hash."""

    id: str
    email: str
    full_name: str
    base_currency: Currency
    email_verified: bool = True
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
