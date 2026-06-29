"""Profile models for learned scan expectations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ScanProfile:
    """Represents the historical fingerprint of expected sequences for a project."""

    project_id: str
    expected_sequences: dict[str, dict[str, Any]] = field(default_factory=dict)
