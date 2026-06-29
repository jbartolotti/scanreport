"""High-level query helpers for archive and prearchive data retrieval."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..models.enums import SessionOrigin, SessionState


def _coerce_date(value: Any) -> str | None:
    """Best-effort conversion of date-like values into an ISO date string."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, str):
        return value
    return str(value)


def _coerce_scans(raw: Any) -> list[dict[str, Any]]:
    """Normalize scan-like payloads into a simple list of name/count pairs."""
    scans: list[dict[str, Any]] = []
    if not raw:
        return scans
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                scans.append(
                    {
                        "sequence_name": str(item.get("sequence_name") or item.get("name") or ""),
                        "dicom_count": int(item.get("dicom_count") or 0),
                    }
                )
    elif isinstance(raw, dict):
        for key, value in raw.items():
            if isinstance(value, dict):
                scans.append({"sequence_name": str(key), "dicom_count": int(value.get("dicom_count") or 0)})
    return scans


def extract_archive_session(raw: Any) -> dict[str, Any] | None:
    """Turn a raw archive experiment into a normalized payload for ingestion."""
    if raw is None:
        return None

    attrs = getattr(raw, "attrs", None)
    if attrs is None:
        attrs = {}

    def read(*names: str) -> Any:
        for name in names:
            if hasattr(raw, name):
                value = getattr(raw, name)
                if callable(value):
                    try:
                        value = value()
                    except TypeError:
                        value = None
                if value not in (None, ""):
                    return value
            if hasattr(attrs, "get") and name in attrs:
                value = attrs.get(name)
                if value not in (None, ""):
                    return value
        return None

    session_id = str(read("id", "session_id", "label", "name") or "")
    if not session_id:
        return None

    return {
        "subject_id": str(read("subject_id", "subject", "subjectId") or ""),
        "project_id": str(read("project_id", "project", "projectId") or ""),
        "session_id": session_id,
        "date": _coerce_date(read("date", "session_date", "xnat:subjectassessordata/date")),
        "origin": SessionOrigin.INTERNAL.value,
        "state": SessionState.ARCHIVED.value,
        "scans": _coerce_scans(read("scans", "scan_data")),
    }


def extract_prearchive_session(raw: Any) -> dict[str, Any] | None:
    """Turn a raw prearchive session into a normalized payload for ingestion."""
    if raw is None:
        return None

    attrs = getattr(raw, "attrs", None)
    if attrs is None:
        attrs = {}

    def read(*names: str) -> Any:
        for name in names:
            if hasattr(raw, name):
                value = getattr(raw, name)
                if callable(value):
                    try:
                        value = value()
                    except TypeError:
                        value = None
                if value not in (None, ""):
                    return value
            if hasattr(attrs, "get") and name in attrs:
                value = attrs.get(name)
                if value not in (None, ""):
                    return value
        return None

    session_id = str(read("id", "session_id", "label", "name") or "")
    if not session_id:
        return None

    return {
        "subject_id": str(read("subject_id", "subject", "subjectId") or ""),
        "project_id": str(read("project_id", "project", "projectId") or ""),
        "session_id": session_id,
        "date": _coerce_date(read("date", "session_date", "xnat:subjectassessordata/date")),
        "origin": SessionOrigin.INTERNAL.value,
        "state": SessionState.PREARCHIVE.value,
        "scans": _coerce_scans(read("scans", "scan_data")),
    }
