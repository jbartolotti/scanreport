"""XNAT client abstraction with read-only authentication support."""

from __future__ import annotations

import logging
import netrc
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

try:
    from pyxnat import Interface
except ImportError:  # pragma: no cover - exercised when pyxnat is unavailable.
    Interface = None  # type: ignore[assignment]

from ..normalization.normalize import normalize_session
from ..models.session import Session
from .dicom_times import compute_session_times, compute_signature
from .queries import extract_archive_session, extract_prearchive_session

logger = logging.getLogger(__name__)


class XNATClient:
    """Thin wrapper for XNAT archive and prearchive queries."""

    def __init__(self, base_url: str, username: str | None = None, password: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.interface: Any | None = None

    def connect(self) -> Any:
        """Authenticate using .netrc or provided credentials."""
        if self.interface is not None:
            return self.interface

        if Interface is None:
            raise RuntimeError("pyxnat is required to connect to XNAT")

        username, password = self._load_credentials()
        print(f"[xnat_audit] Authenticating to XNAT with {'netrc' if username and password else 'anonymous'} credentials")
        try:
            if username and password:
                self.interface = Interface(server=self.base_url, user=username, password=password)
            else:
                self.interface = Interface(server=self.base_url)
            logger.info("Connected to XNAT at %s", self.base_url)
            print(f"[xnat_audit] Connected to XNAT at {self.base_url}")
            return self.interface
        except Exception as exc:  # pragma: no cover - depends on runtime environment
            logger.exception("XNAT connection failed for %s", self.base_url)
            print(f"[xnat_audit] XNAT connection failed: {exc}")
            raise RuntimeError(f"Unable to connect to XNAT at {self.base_url}") from exc

    def get_archive_sessions(self, start_date: str, end_date: str) -> list[dict[str, Any]]:
        """Fetch sessions from the XNAT archive for the requested date range."""
        interface = self.connect()
        try:
            project_items = self._list_collection(interface.select, "projects")
            rows: list[dict[str, Any]] = []
            print(f"[xnat_audit] Found {len(project_items)} project container(s) for archive query")
            for project in project_items:
                experiments = self._safe_call(getattr(project, "experiments", None))
                for item in experiments:
                    try:
                        record = extract_archive_session(item)
                    except Exception as exc:  # pragma: no cover - depends on runtime environment
                        logger.warning("Skipping archive item due to extraction error: %s", exc)
                        continue
                    if record is not None:
                        rows.append(record)
            print(f"[xnat_audit] Retrieved {len(rows)} archive session(s)")
            return rows
        except Exception as exc:  # pragma: no cover - depends on runtime environment
            logger.exception("Archive session query failed")
            print(f"[xnat_audit] Archive query failed: {exc}")
            return []

    def get_prearchive_sessions(self, start_date: str, end_date: str) -> list[dict[str, Any]]:
        """Fetch sessions from the XNAT prearchive for the requested date range."""
        interface = self.connect()
        try:
            candidates = []
            for attr_name in ("prearchive", "sessions", "experiments"):
                candidates.extend(self._list_collection(interface.select, attr_name))
            rows: list[dict[str, Any]] = []
            print(f"[xnat_audit] Inspecting {len(candidates)} prearchive candidate item(s)")
            for item in candidates:
                try:
                    record = extract_prearchive_session(item)
                except Exception as exc:  # pragma: no cover - depends on runtime environment
                    logger.warning("Skipping prearchive item due to extraction error: %s", exc)
                    continue
                if record is not None:
                    rows.append(record)
            print(f"[xnat_audit] Retrieved {len(rows)} prearchive session(s)")
            return rows
        except Exception as exc:  # pragma: no cover - depends on runtime environment
            logger.exception("Prearchive session query failed")
            print(f"[xnat_audit] Prearchive query failed: {exc}")
            return []

    def _load_credentials(self) -> tuple[str | None, str | None]:
        """Read credentials from .netrc for the configured XNAT host."""
        if self.username and self.password:
            return self.username, self.password

        try:
            host = urlparse(self.base_url).hostname or self.base_url
            auth = netrc.netrc().authenticators(host)
            if auth:
                login, account, password = auth
                return login, password
        except (FileNotFoundError, OSError, netrc.NetrcParseError):
            logger.warning("No usable .netrc credentials found for %s", self.base_url)
        return None, None

    def _list_collection(self, selector: Any, attribute_name: str) -> list[Any]:
        """Return a list of items from a pyxnat selector or callable."""
        method = getattr(selector, attribute_name, None)
        if method is None:
            return []
        try:
            value = method()
        except TypeError:
            value = method
        if value is None:
            return []
        if isinstance(value, list):
            return value
        try:
            return list(value)
        except TypeError:
            return [value]

    def _safe_call(self, candidate: Any | None) -> list[Any]:
        """Safely invoke a callable and normalize the result to a list."""
        if candidate is None:
            return []
        if callable(candidate):
            try:
                value = candidate()
            except TypeError:
                return []
        else:
            value = candidate
        if value is None:
            return []
        if isinstance(value, list):
            return value
        try:
            return list(value)
        except TypeError:
            return [value]


def ingest_sessions(client: XNATClient, store: Any, start_date: str, end_date: str) -> list[Session]:
    """Ingest archive and prearchive sessions incrementally using the cache store."""
    processed: list[Session] = []
    archive_records = client.get_archive_sessions(start_date, end_date)
    prearchive_records = client.get_prearchive_sessions(start_date, end_date)

    for raw in [*archive_records, *prearchive_records]:
        session = normalize_session(raw)
        signature = compute_signature(session)
        if store.has_changed(session.session_id, signature):
            start_time, end_time, dicom_count = compute_session_times(session)
            session.start_time = start_time
            session.end_time = end_time
            record = {
                "session_id": session.session_id,
                "project_id": session.project_id,
                "state": session.state.value,
                "start_time": start_time.isoformat() if start_time else None,
                "end_time": end_time.isoformat() if end_time else None,
                "dicom_count": dicom_count,
                "signature": signature,
                "last_checked": datetime.now(timezone.utc).isoformat(),
            }
            store.upsert(record)
            processed.append(session)
        else:
            store.mark_checked(session.session_id)

    return processed
