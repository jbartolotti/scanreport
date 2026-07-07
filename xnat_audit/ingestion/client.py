"""XNAT client abstraction with read-only authentication support."""

from __future__ import annotations

import csv
import io
import logging
import netrc
import time
import traceback
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

try:
    import requests
except ImportError:  # pragma: no cover - exercised when requests is unavailable.
    requests = None  # type: ignore[assignment]

try:
    from pyxnat import Interface
except ImportError:  # pragma: no cover - exercised when pyxnat is unavailable.
    Interface = None  # type: ignore[assignment]

from ..normalization.normalize import normalize_session
from ..models.session import Session
from ..utils import coerce_date, coerce_time
from .dicom_times import compute_session_times, compute_signature
from .queries import _coerce_scans, extract_archive_session, extract_prearchive_session
from .refresh import refresh_cache

logger = logging.getLogger(__name__)
REQUEST_LOGGING_INSTALLED = False
_DETAIL_DEBUG_COUNT = 0


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
        self.request_metrics: dict[str, int] = {
            "total_http_requests": 0,
            "experiment_requests": 0,
            "search_requests": 0,
            "flat_metadata_queries": 0,
            "detailed_experiment_requests": 0,
            "direct_experiment_queries": 0,
            "project_fallback_queries": 0,
            "project_fallback_skipped": 0,
        }
        self._install_request_logging()

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

    def _install_request_logging(self) -> None:
        """Patch requests so XNAT traffic is visible with stack traces for debugging."""
        global REQUEST_LOGGING_INSTALLED
        if REQUEST_LOGGING_INSTALLED or requests is None:
            return

        try:
            from requests.sessions import Session as RequestsSession
        except Exception:
            return

        original_send = RequestsSession.send
        if getattr(RequestsSession, "__xnat_audit_wrapped__", False):
            REQUEST_LOGGING_INSTALLED = True
            return

        def wrapped_send(session: Any, request: Any, **kwargs: Any) -> Any:
            method = getattr(request, "method", "GET") or "GET"
            url = getattr(request, "url", "") or ""
            self.request_metrics["total_http_requests"] += 1

            if "/data/experiments" in url:
                self.request_metrics["experiment_requests"] += 1
                logger.debug("XNAT experiments request: %s %s", method, url)
                print(f"[xnat_audit] Issuing experiments request: {method} {url}")
                #traceback.print_stack(limit=12)
            if "/data/search" in url:
                self.request_metrics["search_requests"] += 1
                logger.debug("XNAT search request: %s %s", method, url)
                print(f"[xnat_audit] Issuing search request: {method} {url}")

            try:
                response = original_send(session, request, **kwargs)
            except Exception as exc:
                if "/data/search" in url:
                    logger.exception("Search request failed for %s", url)
                else:
                    logger.exception("XNAT request failed for %s", url)
                raise exc

            if "/data/search" in url and getattr(response, "status_code", None) and response.status_code >= 400:
                body = getattr(response, "text", "") or ""
                logger.error("Search request failed with %s for %s", response.status_code, url)
                logger.error("Search request payload: %s", getattr(request, "body", None))
                logger.error("Search response body: %s", body)
                print(f"[xnat_audit] Search request failed [{response.status_code}] {url}")
                print(f"[xnat_audit] Search response body: {body}")
                print(f"[xnat_audit] Search request payload: {getattr(request, 'body', None)}")

            return response

        RequestsSession.send = wrapped_send  # type: ignore[assignment]
        RequestsSession.__xnat_audit_wrapped__ = True  # type: ignore[attr-defined]
        REQUEST_LOGGING_INSTALLED = True

    def get_archive_sessions(self, start_date: str, end_date: str) -> list[dict[str, Any]]:
        """Fetch archive sessions using one flat metadata query and lookback filtering before detail fetches."""
        interface = self.connect()
        started_at = time.perf_counter()
        try:
            experiment_rows, used_flat_query = self._query_archive_experiments(interface, start_date, end_date)
            discovered_count = len(experiment_rows)
            lookback_cutoff = date.today() - timedelta(days=self.lookback_days)
            surviving_rows: list[dict[str, Any]] = []

            for row in experiment_rows:
                row_date = coerce_date(str(row.get("date", "")) if row.get("date") is not None else None)
                if row_date is None:
                    continue
                if row_date < lookback_cutoff:
                    continue
                surviving_rows.append(row)

            processed_rows: list[dict[str, Any]] = []
            fully_processed_count = 0
            for row in surviving_rows:
                detail = self._fetch_experiment_details(row.get("id"))
                self.request_metrics["detailed_experiment_requests"] += 1
                record = self._build_archive_record(row, detail)
                if record is not None:
                    processed_rows.append(record)
                    fully_processed_count += 1

            elapsed = time.perf_counter() - started_at
            distinct_projects = len({str(row.get("project", "")).strip() for row in experiment_rows if row.get("project")})
            before_requests = 1 + max(1, distinct_projects)
            after_requests = 1 + max(1, len(surviving_rows))
            query_path = "flat_metadata_query" if used_flat_query else "fallback_metadata_list"
            print(
                "[xnat_audit] Archive query diagnostics: "
                f"experiments_discovered={discovered_count}, experiments_surviving_lookback={len(surviving_rows)}, "
                f"experiments_fully_processed={fully_processed_count}, api_query_time={elapsed:.3f}s"
            )
            print(
                "[xnat_audit] Archive request report: "
                f"total_http_requests={self.request_metrics['total_http_requests']}, "
                f"experiment_requests={self.request_metrics['experiment_requests']}, "
                f"search_requests={self.request_metrics['search_requests']}, "
                f"query_path={query_path}"
            )
            print(
                "[xnat_audit] Archive REST request estimate: "
                f"before_refactor={before_requests}, after_refactor={after_requests}"
            )
            logger.info(
                "Archive query diagnostics: experiments_discovered=%d experiments_surviving_lookback=%d experiments_fully_processed=%d api_query_time=%.3fs",
                discovered_count,
                len(surviving_rows),
                fully_processed_count,
                elapsed,
            )
            logger.info(
                "Archive request report: total_http_requests=%d experiment_requests=%d search_requests=%d query_path=%s",
                self.request_metrics["total_http_requests"],
                self.request_metrics["experiment_requests"],
                self.request_metrics["search_requests"],
                query_path,
            )
            print(f"[xnat_audit] Retrieved {len(processed_rows)} archive session(s)")
            return processed_rows
        except Exception as exc:  # pragma: no cover - depends on runtime environment
            logger.exception("Archive session query failed")
            print(f"[xnat_audit] Archive query failed: {exc}")
            return []

    def get_prearchive_sessions(self, start_date: str, end_date: str) -> list[dict[str, Any]]:
        """Fetch sessions from the XNAT prearchive for the requested date range via the REST API."""
        self.connect()
        try:
            metadata_rows = self._fetch_prearchive_metadata(start_date, end_date)
            discovered_count = len(metadata_rows)
            lookback_cutoff = date.today() - timedelta(days=self.lookback_days)
            surviving_rows: list[dict[str, Any]] = []

            for row in metadata_rows:
                row_date = coerce_date(str(row.get("uploaded", "")) if row.get("uploaded") is not None else None)
                if row_date is None:
                    continue
                if row_date < lookback_cutoff:
                    continue
                surviving_rows.append(row)

            processed_rows: list[dict[str, Any]] = []
            processed_count = 0
            for row in surviving_rows:
                record = self._build_prearchive_record(row)
                if record is not None:
                    processed_rows.append(record)
                    processed_count += 1

            print(
                "[xnat_audit] Prearchive query diagnostics: "
                f"sessions_discovered={discovered_count}, sessions_surviving_filter={len(surviving_rows)}, "
                f"sessions_processed={processed_count}"
            )
            logger.info(
                "Prearchive query diagnostics: sessions_discovered=%d sessions_surviving_filter=%d sessions_processed=%d",
                discovered_count,
                len(surviving_rows),
                processed_count,
            )
            print(f"[xnat_audit] Retrieved {len(processed_rows)} prearchive session(s)")
            return processed_rows
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

    def _query_archive_experiments(self, interface: Any, start_date: str, end_date: str) -> tuple[list[dict[str, Any]], bool]:
        """Fetch archive experiment candidates using a flat metadata query when available."""
        metadata_rows = self._fetch_flat_experiment_metadata(start_date, end_date)
        if metadata_rows is not None:
            self.request_metrics["flat_metadata_queries"] += 1
            return metadata_rows, True

        self.request_metrics["project_fallback_queries"] += 1
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

        self.request_metrics["direct_experiment_queries"] += 1

        if value is None:
            return [], True

        if isinstance(value, list):
            items = value
        else:
            try:
                items = list(value)
            except TypeError:
                items = [value]

        metadata: list[dict[str, Any]] = []
        for item in items:
            row = self._metadata_from_experiment_item(item)
            if row is not None:
                metadata.append(row)
        return metadata, False

    def _fetch_flat_experiment_metadata(self, start_date: str, end_date: str) -> list[dict[str, Any]] | None:
        """Request experiment metadata once as a flat CSV payload and return normalized rows."""
        if requests is None:
            return None

        username, password = self._load_credentials()
        session = requests.Session()
        if username and password:
            session.auth = (username, password)

        params = {
            "columns": "ID,project,label,date",
            "format": "csv",
            "xsiType": "xnat:mrSessionData",
        }

        url = f"{self.base_url}/data/experiments"
        try:
            response = session.get(url, params=params, timeout=30)
            response.raise_for_status()
        except Exception as exc:
            logger.warning("Flat metadata query failed; falling back to item iteration: %s", exc)
            return None

        text = getattr(response, "text", "") or ""
        if not text.strip():
            return []

        rows: list[dict[str, Any]] = []
        reader = csv.DictReader(io.StringIO(text))
        for raw_row in reader:
            row = self._normalize_metadata_row(raw_row)
            if row is not None:
                rows.append(row)
        return rows

    def _normalize_metadata_row(self, raw_row: dict[str, Any]) -> dict[str, Any] | None:
        """Convert a flat CSV row into a normalized archive-metadata dictionary."""
        if not raw_row:
            return None
        row_id = self._first_non_empty(raw_row, ["ID", "id", "session_id", "Session ID"])
        if row_id is None:
            return None
        project = self._first_non_empty(raw_row, ["project", "Project", "project_id", "Project ID"])
        label = self._first_non_empty(raw_row, ["label", "Label"])
        date_value = self._first_non_empty(raw_row, ["date", "Date", "session_date", "Session Date"])
        return {
            "id": str(row_id),
            "project": str(project) if project is not None else "",
            "label": str(label) if label is not None else "",
            "date": str(date_value) if date_value is not None else "",
        }

    def _first_non_empty(self, row: dict[str, Any], names: list[str]) -> Any | None:
        """Return the first non-empty value from a row for the supplied column names."""
        for name in names:
            value = row.get(name)
            if value is None:
                continue
            value = str(value).strip()
            if value:
                return value
        return None

    def _metadata_from_experiment_item(self, item: Any) -> dict[str, Any] | None:
        """Extract archive metadata from a pyxnat-like experiment item without filtering on object attributes."""
        if item is None:
            return None
        if isinstance(item, dict):
            record_id = item.get("id") or item.get("session_id")
            if record_id is None:
                return None
            return {
                "id": str(record_id),
                "project": str(item.get("project", "") or item.get("project_id", "") or ""),
                "label": str(item.get("label", "") or ""),
                "date": str(item.get("date", "") or ""),
            }

        attrs = getattr(item, "attrs", None)
        if attrs is not None and hasattr(attrs, "get"):
            try:
                record_id = attrs.get("ID") or attrs.get("id")
            except Exception:
                record_id = None
            if record_id is None:
                record_id = getattr(item, "id", None)
            project = None
            label = None
            date_value = None
            try:
                project = attrs.get("project") or attrs.get("project_id")
                label = attrs.get("label")
                date_value = attrs.get("date")
            except Exception:
                project = None
                label = None
                date_value = None
            if record_id is None:
                return None
            return {
                "id": str(record_id),
                "project": str(project) if project is not None else "",
                "label": str(label) if label is not None else "",
                "date": str(date_value) if date_value is not None else "",
            }

        record_id = getattr(item, "id", None)
        if record_id is None:
            return None
        return {
            "id": str(record_id),
            "project": "",
            "label": "",
            "date": "",
        }

    def _fetch_prearchive_metadata(
        self,
        start_date: str,
        end_date: str,
    ) -> list[dict[str, Any]]:
        """Fetch prearchive session metadata from XNAT."""

        if requests is None:
            return []

        username, password = self._load_credentials()

        session = requests.Session()
        if username and password:
            session.auth = (username, password)

        url = f"{self.base_url}/data/prearchive/projects?format=json"

        try:
            response = session.get(url, timeout=30)
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            logger.warning(
                "Prearchive metadata fetch failed: %s",
                exc,
            )
            return []

        resultset = payload.get("ResultSet", {})
        records = resultset.get("Result", [])

        print(
            f"[xnat_audit] Raw prearchive records discovered: "
            f"{len(records)}"
        )

        rows: list[dict[str, Any]] = []

        start_dt = coerce_date(start_date)
        end_dt = coerce_date(end_date)

        for item in records:

            if not isinstance(item, dict):
                continue

            row = self._normalize_prearchive_row(item)

            if row is None:
                continue

            uploaded = coerce_date(
                str(row.get("uploaded", ""))
            )

            if uploaded is None:
                logger.debug(
                    "Skipping prearchive item with no parseable uploaded date: %s",
                    row,
                )
                continue

            if start_dt and uploaded < start_dt:
                continue

            if end_dt and uploaded > end_dt:
                continue

            rows.append(row)

        print(
            f"[xnat_audit] Prearchive records surviving date filter: "
            f"{len(rows)}"
        )

        return rows


    def _normalize_prearchive_row(self, item: dict[str, Any]) -> dict[str, Any] | None:
        """Normalize a single prearchive metadata item into a lightweight row."""
        subject = self._first_non_empty(item, ["subject", "subject_id", "Subject", "Subject ID"])
        project = self._first_non_empty(item, ["project", "project_id", "Project", "Project ID"])
        scan_date = self._first_non_empty(item, ["scan_date", "scanDate", "date", "Date"])
        scan_time = self._first_non_empty(item, ["scan_time", "scanTime", "time", "Time"])
        uploaded = self._first_non_empty(item, ["uploaded", "Uploaded", "upload_time", "Upload Time"])
        status = self._first_non_empty(item, ["status", "Status"])
        url = self._first_non_empty(item, ["url", "URL", "uri", "URI"])
        logger.debug("prearchive row: subject=%s", subject)
        if subject is None and project is None and scan_date is None:
            return None
        return {
            "subject": str(subject) if subject is not None else "",
            "project": str(project) if project is not None else "",
            "scan_date": str(scan_date) if scan_date is not None else "",
            "scan_time": str(scan_time) if scan_time is not None else "",
            "uploaded": str(uploaded) if uploaded is not None else "",
            "status": str(status) if status is not None else "",
            "url": str(url) if url is not None else "",
        }

    def _build_prearchive_session_id(self, row: dict[str, Any]) -> str:
        """Create a stable prearchive session identifier from the metadata row."""
        parts = [
            str(row.get("subject", "") or ""),
            str(row.get("project", "") or ""),
            str(row.get("scan_date", "") or ""),
            str(row.get("scan_time", "") or ""),
        ]
        return "prearchive:" + ":".join(part for part in parts if part)

    def _build_prearchive_detail_url(self, row: dict[str, Any], suffix: str) -> str | None:
        """Build a session-specific prearchive endpoint URL for scans or resources."""
        raw_url = str(row.get("url", "") or "").strip()
        if not raw_url:
            return None

        parsed = urlparse(raw_url)
        if parsed.scheme and parsed.netloc:
            base_path = parsed.path.rstrip("/")
            if base_path.startswith("/data/"):
                return f"{parsed.scheme}://{parsed.netloc}{base_path}/{suffix}?format=json"
            if base_path.startswith("/prearchive/"):
                return f"{parsed.scheme}://{parsed.netloc}/data{base_path}/{suffix}?format=json"
            return f"{parsed.scheme}://{parsed.netloc}{base_path}/{suffix}?format=json"

        if raw_url.startswith("/"):
            if raw_url.startswith("/data/"):
                return f"{self.base_url}{raw_url.rstrip('/')}/{suffix}?format=json"
            if raw_url.startswith("/prearchive/"):
                return f"{self.base_url}/data{raw_url.rstrip('/')}/{suffix}?format=json"
            return f"{self.base_url}{raw_url.rstrip('/')}/{suffix}?format=json"

        return None

    def _fetch_prearchive_detail_payload(self, row: dict[str, Any], suffix: str) -> list[dict[str, Any]]:
        """Fetch scan or resource entries for a prearchive session."""
        if requests is None:
            return []

        url = self._build_prearchive_detail_url(row, suffix)
        if not url:
            return []

        username, password = self._load_credentials()
        session = requests.Session()
        if username and password:
            session.auth = (username, password)

        try:
            response = session.get(url, timeout=30)
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            logger.debug("Prearchive %s fetch failed for %s: %s", suffix, row.get("url"), exc)
            return []

        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]

        if isinstance(payload, dict):
            result_set = payload.get("ResultSet")
            if isinstance(result_set, dict):
                result = result_set.get("Result")
                if isinstance(result, list):
                    return [item for item in result if isinstance(item, dict)]
                if isinstance(result, dict):
                    return [result]
            result = payload.get("Result")
            if isinstance(result, list):
                return [item for item in result if isinstance(item, dict)]
            if isinstance(result, dict):
                return [result]
            items = payload.get("items")
            if isinstance(items, list):
                return [item for item in items if isinstance(item, dict)]

        return []

    def _build_prearchive_record(self, row: dict[str, Any]) -> dict[str, Any] | None:
        """Construct a normalized record for a surviving prearchive item."""
        if not row:
            return None

        session_id = self._build_prearchive_session_id(row)
        scan_date = str(row.get("scan_date", "") or "")
        scan_time = str(row.get("scan_time", "") or "")
        fallback_start_time = None
        parsed_date = coerce_date(scan_date)
        parsed_time = coerce_time(scan_time)
        if parsed_date is not None and parsed_time is not None:
            fallback_start_time = datetime.combine(parsed_date, parsed_time)

        scan_rows = self._fetch_prearchive_detail_payload(row, "scans")
        resource_rows = self._fetch_prearchive_detail_payload(row, "resources")

        resource_lookup: dict[str, dict[str, Any]] = {}
        for resource in resource_rows:
            cat_id = self._first_non_empty(resource, ["cat_id", "catID", "CAT_ID", "id"])
            if cat_id is None:
                continue
            resource_lookup[str(cat_id)] = resource

        scans: list[dict[str, Any]] = []
        if not scan_rows:
            logger.debug("Prearchive enrichment failed for %s; using scan_date/scan_time fallback", session_id)
            scans.append(
                {
                    "sequence_name": str(row.get("status", "") or "prearchive"),
                    "sequence_number": None,
                    "series_description": None,
                    "start_date": scan_date,
                    "start_time": scan_time,
                    "dicom_count": 0,
                }
            )
        else:
            for scan in scan_rows:
                sequence_number = self._first_non_empty(scan, ["ID", "id", "sequence_id", "sequenceNumber", "sequence_number"])
                series_description = self._first_non_empty(scan, ["series_description", "seriesDescription", "name", "label"])
                resource = resource_lookup.get(str(sequence_number)) if sequence_number is not None else None
                file_count = 0
                if resource is not None:
                    file_count_value = self._first_non_empty(resource, ["file_count", "fileCount", "count"])
                    if file_count_value is not None:
                        try:
                            file_count = int(file_count_value)
                        except (TypeError, ValueError):
                            file_count = 0
                scans.append(
                    {
                        "sequence_name": str(series_description or sequence_number or ""),
                        "sequence_number": str(sequence_number) if sequence_number is not None else None,
                        "series_description": str(series_description) if series_description is not None else None,
                        "start_date": scan_date,
                        "start_time": scan_time,
                        "dicom_count": file_count,
                    }
                )
        logger.debug("build prearchive record: subject=%s", str(row.get("subject", "") or ""))

        return {
            "session_id": session_id,
            "subject_id": str(row.get("subject", "") or ""),
            "project_id": str(row.get("project", "") or ""),
            "date": scan_date,
            "label": str(row.get("status", "") or ""),
            "origin": "INTERNAL",
            "state": "PREARCHIVE",
            "url": str(row.get("url", "") or ""),
            "start_time": fallback_start_time,
            "scans": scans,
        }

    def _collect_scan_candidates(self, payload: Any) -> list[Any]:
        """Recursively collect scan-like payloads from a detail response for debug tracing."""
        if isinstance(payload, dict):
            candidates: list[Any] = []
            for key, value in payload.items():
                if key in {"scans", "scan", "scan_data"}:
                    if isinstance(value, list):
                        candidates.extend(value)
                    elif isinstance(value, dict):
                        candidates.append(value)
                    elif value is not None:
                        candidates.append(value)
                elif isinstance(value, (dict, list)):
                    candidates.extend(self._collect_scan_candidates(value))
            return candidates
        if isinstance(payload, list):
            candidates = []
            for item in payload:
                candidates.extend(self._collect_scan_candidates(item))
            return candidates
        return []

    def _collect_scan_payload(self, payload: Any) -> list[dict[str, Any]]:
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
                    return [item_value for item_value in child_items if isinstance(item_value, dict)]
        return []

    def _fetch_experiment_details(self, experiment_id: Any) -> dict[str, Any] | None:
        """Fetch a single experiment's detailed metadata for surviving sessions."""
        if experiment_id is None:
            return None
        if requests is None:
            return None

        username, password = self._load_credentials()
        session = requests.Session()
        if username and password:
            session.auth = (username, password)
        url = f"{self.base_url}/data/experiments/{experiment_id}?format=json"
        try:
            response = session.get(url, timeout=30)
            response.raise_for_status()
        except Exception as exc:
            logger.warning("Detailed experiment fetch failed for %s: %s", experiment_id, exc)
            return None

        try:
            payload = response.json()
        except Exception:
            payload = None

        if isinstance(payload, dict):
            global _DETAIL_DEBUG_COUNT
            if logger.isEnabledFor(logging.DEBUG) and _DETAIL_DEBUG_COUNT < 3:
                scan_candidates = self._collect_scan_candidates(payload)
                logger.debug("Session %s detail keys: %s", experiment_id, list(payload.keys()))
                logger.debug("Session %s scan information located: %s", experiment_id, bool(scan_candidates))
                if scan_candidates:
                    logger.debug("Session %s raw scan count: %d", experiment_id, len(scan_candidates))

                items = payload.get("items")
                if isinstance(items, list):
                    logger.debug("Session %s payload items length: %d", experiment_id, len(items))
                    if items:
                        first_item = items[0]
                        if isinstance(first_item, dict):
                            logger.debug("Session %s first item keys: %s", experiment_id, list(first_item.keys()))
                            children = first_item.get("children")
                            if isinstance(children, list) and children:
                                first_child = children[0]
                                if isinstance(first_child, dict):
                                    logger.debug(
                                        "Session %s first child field: %s",
                                        experiment_id,
                                        first_child.get("field"),
                                    )
                                for child in children:
                                    if isinstance(child, dict):
                                        child_field = child.get("field")
                                        if isinstance(child_field, str) and "scan" in child_field.lower():
                                            logger.debug(
                                                "Session %s scan child item count: %d",
                                                experiment_id,
                                                len(child.get("items", []) or []),
                                            )
                                            scan_items = child.get("items")
                                            if isinstance(scan_items, list) and scan_items:
                                                logger.debug(
                                                    "Session %s first scan item discovered: %s",
                                                    experiment_id,
                                                    scan_items[0],
                                                )
                                                break
                _DETAIL_DEBUG_COUNT += 1
            return payload
        return None

    def _build_archive_record(self, row: dict[str, Any], detail: dict[str, Any] | None) -> dict[str, Any] | None:
        """Construct a normalized archive record from a flat metadata row and optional detail payload."""
        experiment_id = row.get("id")
        if experiment_id is None:
            return None
        detail_project = None
        detail_subject = None
        scan_payload: list[dict[str, Any]] = []
        if isinstance(detail, dict):
            items = detail.get("items", [])
            if items and isinstance(items[0], dict):
                data_fields = items[0].get("data_fields", {})
                detail_project = data_fields.get("project") or data_fields.get("project_id")
                detail_subject = data_fields.get("dcmPatientId")
            scan_payload = _coerce_scans(self._collect_scan_payload(detail))
        logger.debug("build archive record: subject=%s", detail_subject)
        record = {
            "session_id": str(experiment_id),
            "subject_id": str(detail_subject) if detail_subject is not None else "",
            "project_id": str(detail_project or row.get("project", "")),
            "date": str(row.get("date", "") or ""),
            "label": str(row.get("label", "") or ""),
            "origin": "INTERNAL",
            "state": "ARCHIVED",
            "scans": scan_payload,
        }

        if logger.isEnabledFor(logging.DEBUG) and _DETAIL_DEBUG_COUNT < 3:
            logger.debug("Archive record %s scan_count=%d", experiment_id, len(scan_payload))
            if scan_payload:
                logger.debug("Archive record %s first scan=%s", experiment_id, scan_payload[0])
        return record

    def _read_project_id(self, project: Any) -> str:
        """Best-effort extraction of a project identifier from a project container."""
        for candidate in (getattr(project, "id", None), getattr(project, "label", None)):
            if candidate:
                return str(candidate)
        attrs = getattr(project, "attrs", None)
        if attrs is not None and hasattr(attrs, "get"):
            try:
                value = attrs.get("ID") or attrs.get("id") or attrs.get("project_id")
            except Exception:
                value = None
            if value:
                return str(value)
        return "<unknown>"

    def _is_in_archive_window(self, item: Any, start_date: str, end_date: str) -> bool:
        """Return True when an experiment is inside the requested date window and not older than the lookback cutoff."""
        effective_start_date = coerce_date(start_date)
        effective_end_date = coerce_date(end_date)
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
    """Compatibility wrapper that preserves the old ingestion signature while routing through the new refresh workflow."""
    refresh_result = refresh_cache(client=client, store=store, lookback_days=30)
    return [Session(subject_id="", project_id="", session_id="", date=date.today(), origin=None, state=None)] * refresh_result["sessions_processed"]
