"""Report generation helpers that operate on the local SQLite registry."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from importlib import resources
from pathlib import Path
from shutil import copyfile
from typing import Any

from .html import build_timeline_events, render_html_report

logger = logging.getLogger("xnat_audit")


def _resolve_week_start(report_date: date | None, report_week: date | None) -> date:
    """Resolve the week anchor date for report generation."""
    if report_week is not None:
        return report_week - timedelta(days=report_week.weekday())
    target_date = report_date or date.today()
    return target_date - timedelta(days=target_date.weekday())


def generate_report(*, store: Any, report_date: date | None = None, report_week: date | None = None, xnat_url: str | None = None, output_path: str | Path | None = None, output_dir: str | Path | None = None) -> dict[str, Any]:
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
        "calendar_events": build_timeline_events(sessions, week_start, xnat_url),
        "pixels_per_minute": 1,
        "xnat_url": xnat_url,
    }

    destination_dir = Path(output_dir or Path.cwd())
    destination_dir.mkdir(parents=True, exist_ok=True)
    if output_path is None:
        output_path = destination_dir / f"report_{week_start:%Y-%m-%d}.html"
    else:
        output_path = Path(output_path)
        if not output_path.is_absolute():
            output_path = destination_dir / output_path

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_html_report(report_payload), encoding="utf-8")

    css_source = None
    try:
        css_source = resources.files("xnat_audit.reporting").joinpath("static/report.css")
        if css_source.is_file():
            css_bytes = css_source.read_bytes()
            css_output_path = output_path.parent / "report.css"
            css_output_path.write_bytes(css_bytes)
            logger.debug("Copied report stylesheet to %s", css_output_path)
    except (AttributeError, FileNotFoundError, ModuleNotFoundError):
        css_source = None

    if css_source is None:
        source_css_path = Path(__file__).resolve().parent / "static" / "report.css"
        if source_css_path.is_file():
            css_output_path = output_path.parent / "report.css"
            copyfile(source_css_path, css_output_path)
            logger.debug("Copied report stylesheet to %s", css_output_path)

    if hasattr(store, "record_report_generation"):
        store.record_report_generation(week_start, str(output_path))

    report_payload["output_path"] = output_path
    report_payload["css_output_path"] = output_path.parent / "report.css"
    return report_payload


def regenerate_dirty_reports(*, store: Any, xnat_url: str | None = None, output_dir: str | Path | None = None) -> list[date]:
    """Regenerate every dirty report week and clear the dirty flag when generation succeeds."""
    generated_weeks: list[date] = []
    destination_dir = Path(output_dir or Path.cwd())
    for week_start, _reason in store.list_dirty_weeks():
        try:
            generate_report(store=store, report_week=week_start, xnat_url=xnat_url, output_dir=destination_dir)
            store.clear_dirty_week(week_start)
            generated_weeks.append(week_start)
        except Exception as exc:  # pragma: no cover - depends on runtime environment
            logger.warning("Failed to regenerate report for week %s: %s", week_start, exc)
    return generated_weeks


def load_sessions_for_report(*, store: Any, report_date: date | None = None, report_week: date | None = None) -> list[dict[str, Any]]:
    """Load the sessions that should appear in a report."""
    if report_week is not None:
        week_start = report_week - timedelta(days=report_week.weekday())
        return store.list_for_week(week_start)
    target_date = report_date or date.today()
    return store.list_for_date(target_date)
