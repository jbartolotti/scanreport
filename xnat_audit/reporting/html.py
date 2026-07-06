"""HTML rendering layer for weekly audit reports."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from html import escape
from pathlib import Path
from string import Template
from typing import Any, Mapping


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


def _render_session_event(session: Mapping[str, Any], start_dt: datetime, end_dt: datetime | None, hour: int) -> str:
    """Render a single session block for the calendar."""
    color_class = _session_color(session)
    point_event = end_dt is None
    time_text = start_dt.strftime("%H:%M")
    if end_dt is not None and end_dt != start_dt:
        time_text = f"{start_dt.strftime('%H:%M')}–{end_dt.strftime('%H:%M')}"

    label = escape(str(session.get("project_id") or "unknown"))
    tooltip = escape(_event_title(session))
    state = escape(str(session.get("state") or "unknown"))
    event_class = "calendar-event calendar-event--point" if point_event else f"calendar-event calendar-event--{color_class}"
    return (
        f"<div class=\"{event_class}\" title=\"{tooltip}\">"
        f"<span class=\"calendar-event__project\">{label}</span>"
        f"<span class=\"calendar-event__time\">{time_text}</span>"
        f"<span class=\"calendar-event__state\">{state}</span>"
        f"</div>"
    )


def _build_day_headers(week_start: date) -> str:
    """Render the header cells for Monday through Sunday."""
    headers: list[str] = []
    for offset in range(7):
        day = week_start + timedelta(days=offset)
        headers.append(f"<th scope=\"col\">{day.strftime('%a')}<br />{day.strftime('%m/%d')}</th>")
    return "".join(headers)


def _build_calendar_rows(week_start: date, sessions: list[Mapping[str, Any]]) -> str:
    """Render the calendar grid content for the chosen week."""
    rows: list[str] = []
    for hour in range(24):
        cells: list[str] = []
        for offset in range(7):
            day = week_start + timedelta(days=offset)
            events: list[str] = []
            for session in sessions:
                start_dt = _parse_session_datetime(session.get("start_time"))
                end_dt = _parse_session_datetime(session.get("end_time"))
                if start_dt is None and end_dt is None:
                    continue
                session_day = None
                if start_dt is not None and start_dt.date() == day:
                    session_day = start_dt.date()
                elif end_dt is not None and end_dt.date() == day:
                    session_day = end_dt.date()
                if session_day != day:
                    continue
                if start_dt is not None and start_dt.date() == day and start_dt.hour == hour:
                    events.append(_render_session_event(session, start_dt, end_dt, hour))
                    continue
                if end_dt is not None and start_dt is not None and start_dt.date() == day and start_dt.hour < hour < end_dt.hour:
                    events.append(_render_session_event(session, start_dt, end_dt, hour))
            cell_content = "".join(events)
            if cell_content:
                cells.append(f"<td class=\"calendar-cell\"><div class=\"calendar-cell__events\">{cell_content}</div></td>")
            else:
                cells.append("<td class=\"calendar-cell calendar-cell--empty\"></td>")
        rows.append(f"<tr><th scope=\"row\">{hour:02d}:00</th>{''.join(cells)}</tr>")
    return "\n".join(rows)


def render_html_report(report_data: Mapping[str, Any], title: str = "Weekly Report") -> str:
    """Render a weekly calendar-style HTML report from a report payload."""
    template_path = Path(__file__).resolve().parent / "templates" / "weekly_report.html"
    template_text = template_path.read_text(encoding="utf-8")
    week_start = report_data.get("week_start")
    week_end = report_data.get("week_end")
    sessions = list(report_data.get("sessions") or [])

    if not isinstance(week_start, date):
        week_start = date.today() - timedelta(days=date.today().weekday())
    if not isinstance(week_end, date):
        week_end = week_start + timedelta(days=6)

    substitutions = {
        "title": escape(title),
        "report_week": escape(f"{week_start:%Y-%m-%d} to {week_end:%Y-%m-%d}"),
        "archive_count": escape(str(report_data.get("archive_session_count", 0))),
        "prearchive_count": escape(str(report_data.get("prearchive_session_count", 0))),
        "total_count": escape(str(report_data.get("session_count", 0))),
        "day_headers": _build_day_headers(week_start),
        "calendar_rows": _build_calendar_rows(week_start, sessions),
    }
    return Template(template_text).substitute(**substitutions)
