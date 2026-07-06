"""HTML rendering layer for weekly audit reports."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from html import escape
from importlib import resources
from pathlib import Path
from string import Template
from typing import Any, Mapping

PIXELS_PER_MINUTE = 1
MINIMUM_MARKER_HEIGHT = 20
OPEN_HOUR = 6
CLOSE_HOUR = 20


def _parse_session_datetime(value: Any) -> datetime | None:
    """Parse an ISO-style datetime string into a datetime object."""
    if value in (None, ""):
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _session_color(session: Mapping[str, Any]) -> str:
    """Resolve a CSS color class for a session state."""
    state = str(session.get("state") or "").upper()
    if state == "ARCHIVED":
        return "archived"
    if state == "PREARCHIVE":
        return "prearchive"
    return "unknown"


def _event_title(session: Mapping[str, Any]) -> str:
    """Create a tooltip-friendly summary for a calendar event."""
    start_time = session.get("start_time") or ""
    end_time = session.get("end_time") or ""
    return "\n".join(
        [
            f"session_id: {session.get('session_id') or ''}",
            f"project_id: {session.get('project_id') or ''}",
            f"state: {session.get('state') or ''}",
            f"dicom_count: {session.get('dicom_count') or ''}",
            f"start_time: {start_time}",
            f"end_time: {end_time}",
        ]
    )


def build_timeline_events(sessions: list[Mapping[str, Any]], week_start: date) -> list[dict[str, Any]]:
    """Build timeline event data with absolute positioning metadata."""
    week_end = week_start + timedelta(days=6)
    events: list[dict[str, Any]] = []
    for session in sessions:
        start_dt = _parse_session_datetime(session.get("start_time"))
        end_dt = _parse_session_datetime(session.get("end_time"))
        if start_dt is None:
            continue

        session_day = start_dt.date()
        if not (week_start <= session_day <= week_end):
            if end_dt is not None and week_start <= end_dt.date() <= week_end:
                session_day = end_dt.date()
            else:
                continue

        minutes_from_midnight = start_dt.hour * 60 + start_dt.minute
        top = max(minutes_from_midnight - (OPEN_HOUR * 60), 0) * PIXELS_PER_MINUTE
        if end_dt is not None and end_dt > start_dt:
            duration_minutes = int((end_dt - start_dt).total_seconds() // 60)
            height = max(duration_minutes, 1) * PIXELS_PER_MINUTE
        else:
            height = MINIMUM_MARKER_HEIGHT

        if start_dt.hour >= CLOSE_HOUR:
            continue
        if end_dt is not None and end_dt.hour >= CLOSE_HOUR and end_dt.minute > 0:
            height = max((CLOSE_HOUR * 60) - (start_dt.hour * 60 + start_dt.minute), 1) * PIXELS_PER_MINUTE

        events.append(
            {
                "session_id": session.get("session_id"),
                "project_id": session.get("project_id"),
                "state": session.get("state"),
                "dicom_count": session.get("dicom_count"),
                "start_time": session.get("start_time"),
                "end_time": session.get("end_time"),
                "day": session_day,
                "day_label": session_day.strftime("%a<br />%m/%d"),
                "top": top,
                "height": height,
                "css_class": _session_color(session),
                "tooltip": _event_title(session),
                "time_label": start_dt.strftime("%H:%M"),
            }
        )
    return events


def _build_day_columns(week_start: date, events: list[dict[str, Any]]) -> str:
    """Render the weekly timeline as seven day columns."""
    columns: list[str] = []
    for offset in range(7):
        day = week_start + timedelta(days=offset)
        day_events = [event for event in events if event["day"] == day]
        event_blocks: list[str] = []
        for event in day_events:
            label = escape(str(event.get("project_id") or "unknown"))
            tooltip = escape(str(event.get("tooltip") or ""))
            event_blocks.append(
                f'<div class="calendar-event {escape(event["css_class"])}" title="{tooltip}" style="top: {event["top"]}px; height: {event["height"]}px;">'
                f'<span class="calendar-event__project">{label}</span>'
                f'<span class="calendar-event__time">{escape(event["time_label"])} </span>'
                f'</div>'
            )
        day_label = day.strftime("%a<br />%m/%d")
        columns.append(
            f'<div class="day-column"><div class="day-column__header">{day_label}</div><div class="day-column__timeline">{"".join(event_blocks)}</div></div>'
        )
    return "\n".join(columns)


def _read_report_asset(relative_path: str) -> str:
    """Read a packaged report asset from either the source tree or an installed package."""
    package_root = Path(__file__).resolve().parent
    candidates = [
        package_root / relative_path,
        Path.cwd() / relative_path,
        Path.cwd() / "xnat_audit" / relative_path,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8")

    try:
        resource = resources.files("xnat_audit.reporting").joinpath(relative_path)
        if resource.is_file():
            return resource.read_text(encoding="utf-8")
    except (AttributeError, FileNotFoundError, ModuleNotFoundError):
        pass

    raise FileNotFoundError(f"Missing report asset: {relative_path}")


def render_html_report(report_data: Mapping[str, Any], title: str = "Weekly Report") -> str:
    """Render a weekly calendar-style HTML report from a report payload."""
    template_text = _read_report_asset("templates/weekly_report.html")
    week_start = report_data.get("week_start")
    week_end = report_data.get("week_end")
    sessions = list(report_data.get("sessions") or [])

    if not isinstance(week_start, date):
        week_start = date.today() - timedelta(days=date.today().weekday())
    if not isinstance(week_end, date):
        week_end = week_start + timedelta(days=6)

    timeline_events = list(report_data.get("calendar_events") or [])
    if not timeline_events:
        timeline_events = build_timeline_events(sessions, week_start)

    substitutions = {
        "title": escape(title),
        "report_week": escape(f"{week_start:%Y-%m-%d} to {week_end:%Y-%m-%d}"),
        "archive_count": escape(str(report_data.get("archive_session_count", 0))),
        "prearchive_count": escape(str(report_data.get("prearchive_session_count", 0))),
        "total_count": escape(str(report_data.get("session_count", 0))),
        "day_columns": _build_day_columns(week_start, timeline_events),
    }
    return Template(template_text).substitute(**substitutions)
