"""XNAT client abstraction with read-only authentication support."""

from __future__ import annotations

from typing import Any


class XNATClient:
    """Thin client wrapper for XNAT archive and prearchive queries."""

    def __init__(self, base_url: str, username: str | None = None, password: str | None = None) -> None:
        self.base_url = base_url
        self.username = username
        self.password = password

    def connect(self) -> None:
        """Authenticate using .netrc or provided credentials."""
        # TODO: implement .netrc-based authentication.
        raise NotImplementedError

    def fetch_archive_sessions(self, start_date: str, end_date: str) -> list[dict[str, Any]]:
        """Fetch sessions from the XNAT archive for the requested date range."""
        # TODO: implement archive query.
        raise NotImplementedError

    def fetch_prearchive_sessions(self, start_date: str, end_date: str) -> list[dict[str, Any]]:
        """Fetch sessions from the XNAT prearchive for the requested date range."""
        # TODO: implement prearchive query.
        raise NotImplementedError
