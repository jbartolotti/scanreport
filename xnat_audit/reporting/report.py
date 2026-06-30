"""Report generation helpers that operate on the local SQLite registry."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any


def generate_report(*, store: Any, report_date: date | None = None, report_week: date | None = None) -> dict[str, Any]:
    """Generate a simple report payload from the local session registry."""
    if report_date is None:
        report_date = date.today()
    if report_week is not None:
        week_start = report_week - timedelta(days=report_week.weekday())
        sessions = store.list_for_week(week_start)
    else:
        week_start = report_date - timedelta(days=report_date.weekday())
        sessions = store.list_for_date(report_date)

    return {
        "report_date": report_date,
        "week_start": week_start,
        "session_count": len(sessions),
        "sessions": sessions,
    }


def load_sessions_for_report(*, store: Any, report_date: date | None = None, report_week: date | None = None) -> list[dict[str, Any]]:
    """Load the sessions that should appear in a report."""
    if report_week is not None:
        week_start = report_week - timedelta(days=report_week.weekday())
        return store.list_for_week(week_start)
    target_date = report_date or date.today()
    return store.list_for_date(target_date)
