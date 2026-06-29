"""Anomaly model definitions."""

from __future__ import annotations

from dataclasses import dataclass

from ..models.enums import AnomalyType


@dataclass
class Anomaly:
    """A single anomaly discovered during reconciliation."""

    type: AnomalyType
    description: str
    severity: str = "medium"
