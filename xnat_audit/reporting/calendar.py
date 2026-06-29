"""Weekly calendar data helpers for HTML reporting."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Sequence

from ..models.session import Session


def build_weekly_calendar_data(sessions: Sequence[Session], week_start: date) -> dict[str, Any]:
    """Shape session data into a weekly calendar structure."""
    days = [week_start + timedelta(days=offset) for offset in range(7)]
    return {
        "week_start": week_start,
        "days": days,
        "sessions": list(sessions),
        "slots": [],
    }
