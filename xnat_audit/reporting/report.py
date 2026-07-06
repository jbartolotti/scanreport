"""Report generation helpers that operate on the local SQLite registry."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .html import build_timeline_events, render_html_report


def _resolve_week_start(report_date: date | None, report_week: date | None) -> date:
    """Resolve the week anchor date for report generation."""
    if report_week is not None:
        return report_week - timedelta(days=report_week.weekday())
    target_date = report_date or date.today()
    return target_date - timedelta(days=target_date.weekday())


def generate_report(*, store: Any, report_date: date | None = None, report_week: date | None = None) -> dict[str, Any]:
    """Generate a weekly HTML report from the local session registry."""
    if report_date is None:
        report_date = date.today()

    week_start = _resolve_week_start(report_date, report_week)
    week_end = week_start + timedelta(days=6)
    sessions = store.list_for_week(week_start)
    archive_count = sum(1 for session in sessions if str(session.get("state") or "").upper() == "ARCHIVED")
    prearchive_count = sum(1 for session in sessions if str(session.get("state") or "").upper() == "PREARCHIVE")

    report_payload = {
        "report_date": report_date,
        "report_week": report_week or report_date,
        "week_start": week_start,
        "week_end": week_end,
        "session_count": len(sessions),
        "archive_session_count": archive_count,
        "prearchive_session_count": prearchive_count,
        "sessions": sessions,
        "calendar_events": build_timeline_events(sessions, week_start),
        "pixels_per_minute": 1,
    }

    output_path = Path.cwd() / "report.html"
    output_path.write_text(render_html_report(report_payload), encoding="utf-8")
    report_payload["output_path"] = output_path
    return report_payload


def load_sessions_for_report(*, store: Any, report_date: date | None = None, report_week: date | None = None) -> list[dict[str, Any]]:
    """Load the sessions that should appear in a report."""
    if report_week is not None:
        week_start = report_week - timedelta(days=report_week.weekday())
        return store.list_for_week(week_start)
    target_date = report_date or date.today()
    return store.list_for_date(target_date)
