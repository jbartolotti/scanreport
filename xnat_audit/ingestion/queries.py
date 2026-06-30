"""High-level query helpers for archive and prearchive data retrieval."""

from __future__ import annotations

import logging
from typing import Any

from ..models.enums import SessionOrigin, SessionState
from ..utils import coerce_date

logger = logging.getLogger(__name__)
_EXTRACT_DEBUG_COUNT = 0
_SCAN_DEBUG_COUNT = 0


def _coerce_date(value: Any) -> str | None:
    """Best-effort conversion of date-like values into an ISO date string."""
    parsed_date = coerce_date(value)
    return parsed_date.isoformat() if parsed_date is not None else None


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

    global _SCAN_DEBUG_COUNT
    if logger.isEnabledFor(logging.DEBUG) and _SCAN_DEBUG_COUNT < 3:
        logger.debug(
            "_coerce_scans: input_type=%s input_count=%d output_count=%d",
            type(raw).__name__,
            len(raw) if hasattr(raw, "__len__") else 1,
            len(scans),
        )
        if scans:
            logger.debug("first scan: %s", scans[0])
        _SCAN_DEBUG_COUNT += 1
    return scans


def _read_attribute(raw: Any, attrs: Any, *names: str) -> Any:
    """Read a field from either the object itself or a mapping-like attrs container."""
    for name in names:
        try:
            value = getattr(raw, name)
        except Exception:
            value = None

        if value is not None and value != "":
            if callable(value):
                try:
                    value = value()
                except TypeError:
                    value = None
            if value not in (None, ""):
                return value

        if isinstance(attrs, dict):
            if name in attrs:
                try:
                    value = attrs[name]
                except Exception as exc:
                    logger.debug("Unable to read attrs[%s]: %s", name, exc)
                    value = None
                if value not in (None, ""):
                    return value
            continue

        if hasattr(attrs, "keys"):
            try:
                keys = attrs.keys()
            except Exception as exc:
                logger.debug("Unable to inspect attrs keys for %s: %s", name, exc)
                keys = None

            if keys is not None and name in keys:
                try:
                    value = attrs[name]
                except Exception as exc:
                    logger.debug("Unable to read attrs[%s]: %s", name, exc)
                    value = None
                if value not in (None, ""):
                    return value
            continue

        if hasattr(attrs, "get"):
            try:
                value = attrs.get(name)
            except Exception as exc:
                logger.debug("pyxnat attrs lookup failed for %s: %s", name, exc)
                value = None
            if value not in (None, ""):
                return value

    return None


def extract_archive_session(raw: Any) -> dict[str, Any] | None:
    """Turn a raw archive experiment into a normalized payload for ingestion."""
    if raw is None:
        return None

    attrs = getattr(raw, "attrs", None)
    if attrs is None:
        attrs = {}

    session_id = str(_read_attribute(raw, attrs, "id", "session_id", "label", "name") or "")
    if not session_id:
        return None

    record = {
        "subject_id": str(_read_attribute(raw, attrs, "subject_id", "subject", "subjectId") or ""),
        "project_id": str(_read_attribute(raw, attrs, "project_id", "project", "projectId") or ""),
        "session_id": session_id,
        "date": _coerce_date(_read_attribute(raw, attrs, "date", "session_date", "xnat:subjectassessordata/date")),
        "origin": SessionOrigin.INTERNAL.value,
        "state": SessionState.ARCHIVED.value,
        "scans": _coerce_scans(_read_attribute(raw, attrs, "scans", "scan_data")),
    }

    global _EXTRACT_DEBUG_COUNT
    if logger.isEnabledFor(logging.DEBUG) and _EXTRACT_DEBUG_COUNT < 3:
        scan_count = len(record.get("scans", []) or [])
        logger.debug("extract_archive_session: session_id=%s scan_count=%d", session_id, scan_count)
        logger.debug("extract_archive_session keys: %s", sorted(record.keys()))
        if scan_count:
            logger.debug("extract_archive_session first scan: %s", record["scans"][0])
        _EXTRACT_DEBUG_COUNT += 1
    return record


def extract_prearchive_session(raw: Any) -> dict[str, Any] | None:
    """Turn a raw prearchive session into a normalized payload for ingestion."""
    if raw is None:
        return None

    attrs = getattr(raw, "attrs", None)
    if attrs is None:
        attrs = {}

    session_id = str(_read_attribute(raw, attrs, "id", "session_id", "label", "name") or "")
    if not session_id:
        return None

    record = {
        "subject_id": str(_read_attribute(raw, attrs, "subject_id", "subject", "subjectId") or ""),
        "project_id": str(_read_attribute(raw, attrs, "project_id", "project", "projectId") or ""),
        "session_id": session_id,
        "date": _coerce_date(_read_attribute(raw, attrs, "date", "session_date", "xnat:subjectassessordata/date")),
        "origin": SessionOrigin.INTERNAL.value,
        "state": SessionState.PREARCHIVE.value,
        "scans": _coerce_scans(_read_attribute(raw, attrs, "scans", "scan_data")),
    }

    global _EXTRACT_DEBUG_COUNT
    if logger.isEnabledFor(logging.DEBUG) and _EXTRACT_DEBUG_COUNT < 3:
        scan_count = len(record.get("scans", []) or [])
        logger.debug("extract_prearchive_session: session_id=%s scan_count=%d", session_id, scan_count)
        logger.debug("extract_prearchive_session keys: %s", sorted(record.keys()))
        if scan_count:
            logger.debug("extract_prearchive_session first scan: %s", record["scans"][0])
        _EXTRACT_DEBUG_COUNT += 1
    return record
