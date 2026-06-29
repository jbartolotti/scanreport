"""Reconciliation engine orchestrating profile building and anomaly detection."""

from __future__ import annotations

from typing import Mapping, Sequence

from ..models.profile import ScanProfile
from ..models.session import Session
from .anomalies import Anomaly
from .rules import ReconciliationRules


class ReconciliationEngine:
    """Coordinate normalization, profile learning, and anomaly detection."""

    def __init__(self, rules: ReconciliationRules | None = None) -> None:
        self.rules = rules or ReconciliationRules()

    def build_profiles(self, sessions: Sequence[Session]) -> dict[str, ScanProfile]:
        """Learn typical scan profiles from historical sessions."""
        # TODO: aggregate sequence frequencies and dicom-count statistics per project.
        return {}

    def evaluate_session(self, session: Session, profiles: Mapping[str, ScanProfile] | None = None) -> list[Anomaly]:
        """Evaluate a single session against expected profiles and rules."""
        # TODO: implement missing/unexpected/duplicate/low-count checks.
        return []

    def detect_anomalies(self, sessions: Sequence[Session]) -> list[Anomaly]:
        """Run anomaly detection across a collection of sessions."""
        # TODO: build profiles first, then evaluate each session.
        return []
