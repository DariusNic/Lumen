from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict

from app.models.user import Currency

# How a snapshot was generated. `scheduled_daily` = APScheduler job;
# `manual` = `POST /api/networth/snapshot`; `backfill` = `scripts/backfill_networth.py`.
SnapshotSource = Literal["scheduled_daily", "manual", "backfill", "on_transaction"]

# Range presets for the history endpoint. Numeric day counts kept on the
# backend so the frontend can't ask for arbitrary windows that blow up the
# response size.
HistoryRange = Literal["1M", "3M", "6M", "1Y", "ALL"]


class AccountBreakdownEntry(BaseModel):
    """One account inside a snapshot's `breakdown`. Balance is always in the
    user's base currency at snapshot time (FX-converted), never native."""

    account_id: str
    name: str
    type: str
    category: Literal["asset", "liability"]
    balance_base: float


class NetWorthSnapshotPublic(BaseModel):
    id: str
    date: datetime
    total_assets: float
    total_liabilities: float
    net_worth: float
    base_currency: Currency
    breakdown: list[AccountBreakdownEntry]
    source: SnapshotSource

    model_config = ConfigDict(from_attributes=True)


class NetWorthCurrent(BaseModel):
    """Response shape for `GET /api/networth`. Combines today's live totals
    with deltas computed against historical snapshots."""

    total_assets: float
    total_liabilities: float
    net_worth: float
    base_currency: Currency
    breakdown: list[AccountBreakdownEntry]
    # Delta vs the snapshot closest to ~30 days ago. None when there's no
    # comparable history (fresh user, no backfill yet).
    delta_30d: Optional[float] = None
    delta_30d_pct: Optional[float] = None
    last_snapshot_date: Optional[datetime] = None
    snapshot_count: int = 0


class NetWorthHistoryPoint(BaseModel):
    date: datetime
    total_assets: float
    total_liabilities: float
    net_worth: float


class NetWorthHistory(BaseModel):
    range: HistoryRange
    points: list[NetWorthHistoryPoint]
    base_currency: Currency
