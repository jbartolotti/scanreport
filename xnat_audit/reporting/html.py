"""HTML rendering layer for weekly audit reports."""

from __future__ import annotations

import json
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


def _format_time(value: Any) -> str:
    """Format a datetime-like value as HH:MM when possible."""
    parsed = _parse_session_datetime(value)
    if parsed is None:
        return ""
    return parsed.strftime("%H:%M")


def _build_xnat_url(session: Mapping[str, Any], base_url: str | None = None) -> str:
    """Build a report-friendly XNAT URL for the session."""
    session_id = str(session.get("session_id") or "")
    if not session_id:
        return ""

    if base_url:
        base = base_url.rstrip("/")
    else:
        base = "https://xnat.kumc.edu"

    state = str(session.get("state") or "").upper()
    if state == "ARCHIVED":
        return f"{base}/data/experiments/{session_id}"
    if state == "PREARCHIVE":
        prearchive_url = str(session.get("xnat_url") or session.get("prearchive_url") or "")
        if prearchive_url:
            return prearchive_url
        return f"{base}/data/prearchive/experiments/{session_id}"
    return ""


def _event_title(session: Mapping[str, Any]) -> str:
    """Create a tooltip-friendly summary for a calendar event."""
    return "\n".join(
        [
            f"Subject ID: {session.get('subject_id') or ''}",
            f"Project ID: {session.get('project_id') or ''}",
            f"Start Time: {_format_time(session.get('start_time'))}",
            f"End Time: {_format_time(session.get('end_time'))}",
            f"DICOM Count: {session.get('dicom_count') or ''}",
        ]
    )


def build_timeline_events(sessions: list[Mapping[str, Any]], week_start: date, xnat_url: str | None = None) -> list[dict[str, Any]]:
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

        if session_day.weekday() >= 5:
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

        start_label = start_dt.strftime("%H:%M")
        end_label = ""
        if end_dt is not None and end_dt > start_dt:
            end_label = end_dt.strftime("%H:%M")
            display_time = f"{start_label} - {end_label}"
        else:
            display_time = start_label

        scan_profile_value = session.get("scan_profile") or ""
        scan_profile_text = scan_profile_value if isinstance(scan_profile_value, str) else json.dumps(scan_profile_value)

        events.append(
            {
                "session_id": session.get("session_id"),
                "subject_id": session.get("subject_id"),
                "project_id": session.get("project_id"),
                "state": session.get("state"),
                "dicom_count": session.get("dicom_count"),
                "start_time": session.get("start_time"),
                "end_time": session.get("end_time"),
                "scan_profile": scan_profile_text,
                "xnat_url": _build_xnat_url(session, xnat_url),
                "day": session_day,
                "day_label": session_day.strftime("%a<br />%m/%d"),
                "top": top,
                "height": height,
                "css_class": _session_color(session),
                "tooltip": _event_title(session),
                "time_label": start_label,
                "display_time": display_time,
            }
        )
    return events


def _build_day_columns(week_start: date, events: list[dict[str, Any]]) -> str:
    """Render the weekly timeline as Monday through Friday day columns."""
    columns: list[str] = []
    for offset in range(5):
        day = week_start + timedelta(days=offset)
        day_events = [event for event in events if event["day"] == day]
        event_blocks: list[str] = []
        for event in day_events:
            subject_id = escape(str(event.get("subject_id") or "unknown"))
            project_id = escape(str(event.get("project_id") or "unknown"))
            tooltip = escape(str(event.get("tooltip") or ""))
            start_label = escape(str(event.get("time_label") or ""))
            display_time = escape(str(event.get("display_time") or ""))
            event_blocks.append(
                f'<div class="calendar-event {escape(event["css_class"])}" '
                f'title="{tooltip}" '
                f'data-session-id="{escape(str(event.get("session_id") or ""))}" '
                f'data-subject-id="{subject_id}" '
                f'data-project-id="{project_id}" '
                f'data-state="{escape(str(event.get("state") or ""))}" '
                f'data-start-time="{escape(str(event.get("start_time") or ""))}" '
                f'data-end-time="{escape(str(event.get("end_time") or ""))}" '
                f'data-dicom-count="{escape(str(event.get("dicom_count") or ""))}" '
                f'data-scan-profile="{escape(str(event.get("scan_profile") or ""))}" '
                f'data-xnat-url="{escape(str(event.get("xnat_url") or ""))}" '
                f'style="top: {event["top"]}px; height: {event["height"]}px;">'
                f'<span class="calendar-event__project">{project_id} - {subject_id}</span>'
                f'<span class="calendar-event__time">{display_time}</span>'
                f'<span class="calendar-event__time calendar-event__time--small">{start_label}</span>'
                f'</div>'
            )
        day_label = day.strftime("%a<br />%m/%d")
        columns.append(
            f'<div class="day-column"><div class="day-column__header">{day_label}</div><div class="day-column__timeline">{"".join(event_blocks)}</div></div>'
        )
    return "\n".join(columns)


def _build_hour_labels() -> str:
    """Render the vertical hour labels for the visible timeline."""
    labels: list[str] = []
    for hour in range(OPEN_HOUR, CLOSE_HOUR + 1):
        top = (hour - OPEN_HOUR) * 60
        labels.append(f'<div class="timeline-label" style="top: {top}px;">{hour:02d}:00</div>')
    return "".join(labels)


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
    xnat_url = report_data.get("xnat_url")

    if not isinstance(week_start, date):
        week_start = date.today() - timedelta(days=date.today().weekday())
    if not isinstance(week_end, date):
        week_end = week_start + timedelta(days=6)

    timeline_events = list(report_data.get("calendar_events") or [])
    if not timeline_events:
        timeline_events = build_timeline_events(sessions, week_start, xnat_url)

    previous_week = week_start - timedelta(days=7)
    next_week = week_start + timedelta(days=7)

    substitutions = {
        "title": escape(title),
        "report_week": escape(f"{week_start:%Y-%m-%d} to {week_end:%Y-%m-%d}"),
        "archive_count": escape(str(report_data.get("archive_session_count", 0))),
        "prearchive_count": escape(str(report_data.get("prearchive_session_count", 0))),
        "total_count": escape(str(report_data.get("session_count", 0))),
        "week_navigation": (
            f'<div class="week-nav">'
            f'<a href="report_{previous_week:%Y-%m-%d}.html">Previous Week</a>'
            f'<a href="report_{next_week:%Y-%m-%d}.html">Next Week</a>'
            f'</div>'
        ),
        "timeline_hours": _build_hour_labels(),
        "calendar_columns": _build_day_columns(week_start, timeline_events),
    }
    return Template(template_text).substitute(**substitutions)
