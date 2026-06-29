"""XNAT client abstraction with read-only authentication support."""

from __future__ import annotations

import logging
import netrc
import time
from datetime import date, datetime, timedelta, timezone
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

    def __init__(
        self,
        base_url: str,
        username: str | None = None,
        password: str | None = None,
        lookback_days: int = 30,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.lookback_days = lookback_days
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
        started_at = time.perf_counter()
        try:
            project_items = self._list_collection(interface.select, "projects")
            projects_found = len(project_items)
            print(f"[xnat_audit] Found {projects_found} project container(s) for archive query")

            experiment_items, used_direct_query = self._query_archive_experiments(interface, start_date, end_date)
            if not experiment_items and projects_found:
                experiment_items = []
                for project in project_items:
                    experiments = self._safe_call(getattr(project, "experiments", None))
                    experiment_items.extend(experiments)
                used_direct_query = False

            examined_count = len(experiment_items)
            retained_rows: list[dict[str, Any]] = []
            retained_count = 0

            for item in experiment_items:
                if not self._is_in_archive_window(item, start_date, end_date):
                    continue
                retained_count += 1
                try:
                    record = extract_archive_session(item)
                except Exception as exc:  # pragma: no cover - depends on runtime environment
                    logger.warning("Skipping archive item due to extraction error: %s", exc)
                    continue
                if record is not None:
                    retained_rows.append(record)

            elapsed = time.perf_counter() - started_at
            current_requests = 1 + projects_found
            optimized_requests = 2 if used_direct_query else 1 + projects_found
            print(
                "[xnat_audit] Archive query diagnostics: "
                f"projects_found={projects_found}, experiments_examined={examined_count}, "
                f"experiments_retained={retained_count}, api_query_time={elapsed:.3f}s"
            )
            print(
                "[xnat_audit] Archive query REST request estimate: "
                f"current={current_requests}, optimized={optimized_requests}"
            )
            logger.info(
                "Archive query diagnostics: projects_found=%d experiments_examined=%d experiments_retained=%d api_query_time=%.3fs",
                projects_found,
                examined_count,
                retained_count,
                elapsed,
            )
            print(f"[xnat_audit] Retrieved {len(retained_rows)} archive session(s)")
            return retained_rows
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

    def _query_archive_experiments(self, interface: Any, start_date: str, end_date: str) -> tuple[list[Any], bool]:
        """Fetch archive experiment candidates, preferring a direct experiments query over project iteration."""
        selector = getattr(interface, "select", None)
        if selector is None:
            return [], False

        method = getattr(selector, "experiments", None)
        if method is None:
            return [], False

        try:
            value = method()
        except TypeError:
            return [], False

        if value is None:
            return [], True

        value = self._apply_date_constraints(value, start_date, end_date)

        if isinstance(value, list):
            return value, True

        try:
            items = list(value)
        except TypeError:
            return [value], True

        return items, True

    def _apply_date_constraints(self, value: Any, start_date: str, end_date: str) -> Any:
        """Best-effort use of pyxnat's native filtering hooks when available."""
        for method_name in ("where", "search", "filter"):
            method = getattr(value, method_name, None)
            if not callable(method):
                continue
            for args, kwargs in (
                ((start_date, end_date), {}),
                ((start_date,), {}),
                ((), {"start_date": start_date, "end_date": end_date}),
                ((), {"from_date": start_date, "to_date": end_date}),
            ):
                try:
                    result = method(*args, **kwargs)
                except TypeError:
                    continue
                except Exception:
                    continue
                if result is not None:
                    return result
        return value

    def _is_in_archive_window(self, item: Any, start_date: str, end_date: str) -> bool:
        """Return True when an experiment is inside the requested date window and not older than the lookback cutoff."""
        effective_start_date = self._coerce_date(start_date)
        effective_end_date = self._coerce_date(end_date)
        if effective_start_date is None:
            effective_start_date = date.today() - timedelta(days=self.lookback_days)
        if effective_end_date is None:
            effective_end_date = date.today()

        if effective_start_date > effective_end_date:
            effective_start_date, effective_end_date = effective_end_date, effective_start_date

        lookback_cutoff = date.today() - timedelta(days=self.lookback_days)
        candidate_start = self._read_experiment_date(item)
        if candidate_start is None:
            return False

        if candidate_start < lookback_cutoff:
            return False

        if candidate_start < effective_start_date:
            return False

        if candidate_start > effective_end_date:
            return False

        return True

    def _read_experiment_date(self, item: Any) -> date | None:
        """Best-effort extraction of an experiment date from either attrs or object attributes."""
        attrs = getattr(item, "attrs", None)
        for name in ("date", "session_date", "xnat:subjectassessordata/date"):
            value = None
            if hasattr(item, name):
                value = getattr(item, name)
            elif attrs is not None and hasattr(attrs, "get"):
                try:
                    value = attrs.get(name)
                except Exception:
                    value = None
            if value is None:
                continue
            if isinstance(value, datetime):
                return value.date()
            if isinstance(value, date):
                return value
            if isinstance(value, str):
                try:
                    return datetime.fromisoformat(value).date()
                except ValueError:
                    try:
                        return datetime.strptime(value, "%Y-%m-%d").date()
                    except ValueError:
                        return None
        return None

    def _coerce_date(self, value: str | None) -> date | None:
        """Parse a string into a date value when possible."""
        if value is None:
            return None
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value).date()
            except ValueError:
                try:
                    return datetime.strptime(value, "%Y-%m-%d").date()
                except ValueError:
                    return None
        return None

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
