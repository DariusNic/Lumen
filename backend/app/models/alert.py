"""Alerts are computed on-read from current state (no materialized rows).

Each alert has a deterministic, stable ID derived from its source — e.g.
`budget_overrun:5f...:2026-05` for a May 2026 overrun on category 5f...
This lets "mark as read" persist across requests without storing the alert
body itself: only the dismissed/read ID set lives in `alert_states`.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict


Severity = Literal["critical", "warning", "info"]
# Frontend maps `icon` to a lucide component. Keep this list short and stable
# — adding new icons requires touching the React mapping table too.
AlertIcon = Literal[
    "pie-chart", "alert-triangle", "trending-up", "trending-down",
    "flag", "repeat", "calendar", "wallet",
]
AlertGroup = Literal["Today", "Yesterday", "This week", "Earlier"]
AlertSource = Literal[
    "budget_overrun",
    "goal_behind",
    "recurring_due",
    "stale_account",
    "signal_change",
]


class AlertPublic(BaseModel):
    id: str
    severity: Severity
    icon: AlertIcon
    title: str
    message: str
    timestamp: datetime
    group: AlertGroup
    unread: bool
    link: str
    source: AlertSource

    model_config = ConfigDict(from_attributes=True)


class AlertList(BaseModel):
    alerts: list[AlertPublic]
    unread_count: int


class AlertReadRequest(BaseModel):
    """POST /alerts/read — body lists the ids to mark as read.

    Empty list means "mark every visible alert as read"; the service resolves
    that by recomputing the current set and adding all of them.
    """
    ids: Optional[list[str]] = None
