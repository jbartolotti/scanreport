"""High-level query helpers for archive and prearchive data retrieval."""

from __future__ import annotations

import logging
from typing import Any

from ..models.enums import SessionOrigin, SessionState
from ..utils import coerce_date, coerce_datetime

logger = logging.getLogger(__name__)
_EXTRACT_DEBUG_COUNT = 0
_SCAN_DEBUG_COUNT = 0


def _coerce_date(value: Any) -> str | None:
    """Best-effort conversion of date-like values into an ISO date string."""
    parsed_date = coerce_date(value)
    return parsed_date.isoformat() if parsed_date is not None else None


def _extract_scan_items(payload: Any) -> list[dict[str, Any]]:
    """Extract scan items from the nested XNAT experiment detail payload."""
    if not isinstance(payload, dict):
        return []

    items = payload.get("items")
    if not isinstance(items, list):
        return []

    for item in items:
        if not isinstance(item, dict):
            continue
        children = item.get("children")
        if not isinstance(children, list):
            continue
        for child in children:
            if not isinstance(child, dict):
                continue
            if child.get("field") != "scans/scan":
                continue
            child_items = child.get("items")
            if isinstance(child_items, list):
                return [scan_item for scan_item in child_items if isinstance(scan_item, dict)]
    return []


def _extract_scan_file_count(item: Any) -> int:
    """Best-effort extraction of the scan file_count from nested payload structures."""
    if item is None:
        return 0
    if isinstance(item, dict):
        if "file_count" in item and item.get("file_count") is not None:
            try:
                return int(item.get("file_count") or 0)
            except (TypeError, ValueError):
                return 0
        for value in item.values():
            if isinstance(value, (dict, list)):
                count = _extract_scan_file_count(value)
                if count:
                    return count
        return 0
    if isinstance(item, list):
        for child in item:
            count = _extract_scan_file_count(child)
            if count:
                return count
    return 0


def _extract_data_field_value(data_fields: dict[str, Any] | None, *names: str) -> Any:
    """Read a value from a nested data_fields payload using a list of possible keys."""
    if not isinstance(data_fields, dict):
        return None
    for name in names:
        if name in data_fields and data_fields.get(name) not in (None, ""):
            return data_fields.get(name)
    for name in names:
        if "/" in name:
            base, suffix = name.split("/", 1)
            if base in data_fields and isinstance(data_fields.get(base), dict):
                nested = data_fields.get(base)
                if isinstance(nested, dict) and suffix in nested and nested.get(suffix) not in (None, ""):
                    return nested.get(suffix)
    return None


def _coerce_scans(raw: Any) -> list[dict[str, Any]]:
    """Normalize scan-like payloads into a rich list for timing and profiling."""
    scans: list[dict[str, Any]] = []
    if not raw:
        return scans

    raw_items: list[Any] = []
    if isinstance(raw, list):
        raw_items = raw
    elif isinstance(raw, dict):
        raw_items = [raw]

    for item in raw_items:
        if not isinstance(item, dict):
            continue

        data_fields = item.get("data_fields")
        if not isinstance(data_fields, dict):
            data_fields = {}

        sequence_number = _extract_data_field_value(data_fields, "ID", "id", "sequence_id")
        protocol_name = _extract_data_field_value(data_fields, "protocolName", "protocol_name")
        series_description = _extract_data_field_value(data_fields, "series_description", "seriesDescription")
        raw_start_time = _extract_data_field_value(data_fields, "startTime", "start_time")
        start_date = _extract_data_field_value(data_fields, "start_date", "startDate")
        frames = _extract_data_field_value(data_fields, "frames")
        tr = _extract_data_field_value(data_fields, "parameters/tr", "tr")
        coerced_start_time = coerce_datetime(raw_start_time)
        logger.debug(
            "_coerce_scans start_time pre=%r post=%r",
            raw_start_time,
            coerced_start_time,
        )

        try:
            frame_value = float(frames) if frames not in (None, "") else None
        except (TypeError, ValueError):
            frame_value = None
        try:
            tr_value = float(tr) if tr not in (None, "") else None
        except (TypeError, ValueError):
            tr_value = None

        if not any(
            [sequence_number, protocol_name, series_description, raw_start_time, start_date, frames, tr]
        ):
            continue

        scans.append(
            {
                "sequence_name": str(
                    series_description
                    or protocol_name
                    or sequence_number
                    or item.get("name")
                    or item.get("sequence_name")
                    or ""
                ),
                "sequence_number": sequence_number,
                "protocol_name": protocol_name,
                "series_description": series_description,
                "start_time": coerced_start_time,
                "start_date": coerce_date(start_date),
                "frames": frame_value,
                "tr": tr_value,
                "dicom_count": _extract_scan_file_count(item),
            }
        )

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

    scan_payload = _extract_scan_items(raw) if isinstance(raw, dict) else None
    if scan_payload is None:
        scan_payload = _read_attribute(raw, attrs, "scans", "scan_data")

    record = {
        "subject_id": str(_read_attribute(raw, attrs, "subject_id", "subject", "subjectId") or ""),
        "project_id": str(_read_attribute(raw, attrs, "project_id", "project", "projectId") or ""),
        "session_id": session_id,
        "date": _coerce_date(_read_attribute(raw, attrs, "date", "session_date", "xnat:subjectassessordata/date")),
        "origin": SessionOrigin.INTERNAL.value,
        "state": SessionState.ARCHIVED.value,
        "scans": _coerce_scans(scan_payload),
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

    scan_payload = _extract_scan_items(raw) if isinstance(raw, dict) else None
    if scan_payload is None:
        scan_payload = _read_attribute(raw, attrs, "scans", "scan_data")

    record = {
        "subject_id": str(_read_attribute(raw, attrs, "subject_id", "subject", "subjectId") or ""),
        "project_id": str(_read_attribute(raw, attrs, "project_id", "project", "projectId") or ""),
        "session_id": session_id,
        "date": _coerce_date(_read_attribute(raw, attrs, "date", "session_date", "xnat:subjectassessordata/date")),
        "origin": SessionOrigin.INTERNAL.value,
        "state": SessionState.PREARCHIVE.value,
        "scans": _coerce_scans(scan_payload),
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
