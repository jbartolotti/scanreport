"""Snapshot persistence for processed session collections."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

from ..models.session import Session


def save_snapshot(path: str | Path, sessions: Sequence[Session]) -> None:
    """Save processed sessions as a JSON snapshot."""
    # TODO: serialize session objects in a stable schema.
    payload = [session.__dict__ for session in sessions]
    Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_snapshot(path: str | Path) -> list[Session]:
    """Load sessions from a JSON snapshot."""
    # TODO: restore Session instances from the stored schema.
    raise NotImplementedError
