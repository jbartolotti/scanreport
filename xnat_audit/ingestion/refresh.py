"""Refresh workflow for ingesting recent XNAT sessions into the local registry."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from ..normalization.normalize import normalize_session
from ..models.session import Session
from .dicom_times import compute_session_times, compute_signature

logger = logging.getLogger(__name__)


def _week_start_for_date(value: date | None) -> str | None:
    """Return the Monday-based week anchor for a date."""
    if value is None:
        return None
    return (value - timedelta(days=value.weekday())).isoformat()


def refresh_cache(*, client: Any, store: Any, lookback_days: int) -> dict[str, int]:
    """Refresh the local session registry from XNAT archives and prearchives."""
    today = date.today()
    start_date = (today - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    end_date = today.strftime("%Y-%m-%d")

    archive_records = client.get_archive_sessions(start_date, end_date)
    prearchive_records = client.get_prearchive_sessions(start_date, end_date)

    sessions_discovered = len(archive_records) + len(prearchive_records)
    sessions_updated = 0
    sessions_processed = 0

    for raw in [*archive_records, *prearchive_records]:
        session = normalize_session(raw)
        new_signature = compute_signature(session)
        old_signature = store.get_signature(session.session_id)
        sessions_processed += 1
        changed = old_signature is None or old_signature != new_signature
        if changed:
            reason = "new_session" if old_signature is None else "signature_changed"
            week_start = _week_start_for_date(session.date)
            if week_start is not None:
                store.mark_dirty_week(week_start, reason)

        if changed:
            start_time, end_time, dicom_count, scan_profile = compute_session_times(session)
            logger.debug(
                "refresh_cache session=%s start_time_pre=%r end_time_pre=%r",
                session.session_id,
                start_time,
                end_time,
            )
            session.start_time = start_time
            session.end_time = end_time
            logger.debug(
                "refresh_cache session=%s start_time_post=%r end_time_post=%r",
                session.session_id,
                session.start_time,
                session.end_time,
            )
            record = {
                "session_id": session.session_id,
                "subject_id": session.subject_id,
                "project_id": session.project_id,
                "state": session.state.value,
                "start_time": start_time.isoformat() if start_time else None,
                "end_time": end_time.isoformat() if end_time else None,
                "insert_date": session.insert_date.isoformat() if session.insert_date else None,
                "week_start": _week_start_for_date(session.date),
                "dicom_count": dicom_count,
                "scan_profile": scan_profile,
                "signature": new_signature,
                "last_checked": date.today().isoformat(),
            }
            store.upsert(record)
            sessions_updated += 1
        else:
            store.mark_checked(session.session_id)

    return {
        "sessions_discovered": sessions_discovered,
        "sessions_processed": sessions_processed,
        "sessions_updated": sessions_updated,
    }


def ingest_recent_sessions(*, client: Any, store: Any, lookback_days: int) -> dict[str, int]:
    """Compatibility entrypoint for the new refresh workflow."""
    return refresh_cache(client=client, store=store, lookback_days=lookback_days)
