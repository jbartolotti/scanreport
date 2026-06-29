"""Shared enums for session state, origin, and anomaly types."""

from __future__ import annotations

from enum import Enum


class SessionState(str, Enum):
    """Lifecycle state of a session within the XNAT workflow."""

    PREARCHIVE = "PREARCHIVE"
    ARCHIVED = "ARCHIVED"


class SessionOrigin(str, Enum):
    """Origin of the scan data source."""

    INTERNAL = "INTERNAL"
    EXTERNAL = "EXTERNAL"


class AnomalyType(str, Enum):
    """Supported anomaly categories for reconciliation."""

    MISSING = "MISSING"
    DUPLICATE = "DUPLICATE"
    UNEXPECTED = "UNEXPECTED"
    LOW_COUNT = "LOW_COUNT"
