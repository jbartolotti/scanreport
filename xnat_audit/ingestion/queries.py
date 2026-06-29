"""High-level query helpers for archive and prearchive data retrieval."""

from __future__ import annotations

from typing import Any


def fetch_archive_sessions(client: Any, start_date: str, end_date: str) -> list[dict[str, Any]]:
    """Wrap XNATClient archive calls in a stable interface."""
    # TODO: implement this wrapper around the client.
    raise NotImplementedError


def fetch_prearchive_sessions(client: Any, start_date: str, end_date: str) -> list[dict[str, Any]]:
    """Wrap XNATClient prearchive calls in a stable interface."""
    # TODO: implement this wrapper around the client.
    raise NotImplementedError
