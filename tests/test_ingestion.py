import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from typing import Optional
from unittest.mock import patch

from xnat_audit.ingestion.client import XNATClient
from xnat_audit.ingestion.dicom_times import compute_session_times, compute_signature
from xnat_audit.ingestion.queries import _coerce_scans, _extract_scan_items, extract_archive_session, extract_prearchive_session
from xnat_audit.ingestion.refresh import refresh_cache
from xnat_audit.normalization.normalize import normalize_session
from xnat_audit.models.enums import SessionOrigin, SessionState
from xnat_audit.models.scan import Scan
from xnat_audit.models.session import Session
from xnat_audit.storage.sqlite_store import SessionTimeStore
from xnat_audit.utils import coerce_date


class IngestionWorkflowTests(unittest.TestCase):
    def test_signature_is_stable(self) -> None:
        session = Session(
            subject_id="SUBJ1",
            project_id="PROJ1",
            session_id="SESSION1",
            date=date(2026, 6, 29),
            origin=SessionOrigin.INTERNAL,
            state=SessionState.ARCHIVED,
            scans=[Scan(sequence_name="T1", normalized_name="t1", dicom_count=20)],
        )

        first = compute_signature(session)
        second = compute_signature(session)

        self.assertEqual(first, second)

    def test_store_detects_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "session_times.db")
            store = SessionTimeStore(db_path)
            session = Session(
                subject_id="SUBJ2",
                project_id="PROJ2",
                session_id="SESSION2",
                date=date(2026, 6, 29),
                origin=SessionOrigin.INTERNAL,
                state=SessionState.PREARCHIVE,
                scans=[Scan(sequence_name="T2", normalized_name="t2", dicom_count=10)],
            )

            signature = compute_signature(session)
            self.assertTrue(store.has_changed(session.session_id, signature))

            store.upsert(
                {
                    "session_id": session.session_id,
                    "project_id": session.project_id,
                    "state": session.state.value,
                    "start_time": None,
                    "end_time": None,
                    "dicom_count": 10,
                    "signature": signature,
                    "last_checked": "2026-06-29T00:00:00+00:00",
                }
            )
            self.assertFalse(store.has_changed(session.session_id, signature))
            store.close()

    def test_coerce_date_handles_multiple_common_formats(self) -> None:
        self.assertEqual(coerce_date("2026-06-30"), date(2026, 6, 30))
        self.assertEqual(coerce_date("2026-06-30 12:34:56"), date(2026, 6, 30))
        self.assertEqual(coerce_date("06/30/2026"), date(2026, 6, 30))
        self.assertEqual(coerce_date(datetime(2026, 6, 30, 8, 15, 0)), date(2026, 6, 30))

    def test_nested_scan_payload_survives_full_ingestion_path(self) -> None:
        payload = {
            "items": [
                {
                    "children": [
                        {
                            "field": "scans/scan",
                            "items": [
                                {
                                    "data_fields": {
                                        "ID": "1",
                                        "protocolName": "MPRAGE",
                                        "series_description": "MPRAGE",
                                        "startTime": "2026-06-30T09:00:00",
                                        "start_date": "2026-06-30",
                                        "frames": "100",
                                        "parameters": {"tr": "3.0"},
                                    },
                                    "children": [{"file_count": 12}],
                                }
                            ],
                        }
                    ]
                }
            ]
        }

        scan_items = _extract_scan_items(payload)
        self.assertEqual(len(scan_items), 1)

        normalized_scans = _coerce_scans(scan_items)
        self.assertEqual(len(normalized_scans), 1)
        self.assertEqual(normalized_scans[0]["dicom_count"], 12)
        self.assertEqual(normalized_scans[0]["protocol_name"], "MPRAGE")
        self.assertEqual(normalized_scans[0]["frames"], 100.0)
        self.assertEqual(normalized_scans[0]["tr"], 3.0)

        session = normalize_session(
            {
                "session_id": "SESSION7",
                "subject_id": "SUBJ7",
                "project_id": "PROJ7",
                "date": "2026-06-30",
                "scans": normalized_scans,
            }
        )
        self.assertEqual(len(session.scans), 1)
        self.assertEqual(session.scans[0].protocol_name, "MPRAGE")
        self.assertEqual(session.scans[0].dicom_count, 12)

        start_time, end_time, dicom_count, scan_profile = compute_session_times(session)
        self.assertIsNotNone(start_time)
        self.assertIsNotNone(end_time)
        self.assertEqual(dicom_count, 12)
        self.assertIn("MPRAGE", scan_profile)

    def test_compute_session_times_returns_positive_values(self) -> None:
        session = Session(
            subject_id="SUBJ3",
            project_id="PROJ3",
            session_id="SESSION3",
            date=date(2026, 6, 29),
            origin=SessionOrigin.EXTERNAL,
            state=SessionState.PREARCHIVE,
            scans=[Scan(sequence_name="FLAIR", normalized_name="flair", dicom_count=5)],
        )

        start_time, end_time, dicom_count, scan_profile = compute_session_times(session)
        self.assertGreaterEqual(dicom_count, 1)
        self.assertLessEqual(start_time, end_time)
        self.assertIsInstance(scan_profile, str)

    def test_compute_session_times_combines_scan_date_and_time(self) -> None:
        session = Session(
            subject_id="SUBJ8",
            project_id="PROJ8",
            session_id="SESSION8",
            date=date(2026, 6, 30),
            origin=SessionOrigin.INTERNAL,
            state=SessionState.ARCHIVED,
            scans=[
                Scan(
                    sequence_name="T1",
                    normalized_name="t1",
                    dicom_count=3,
                    start_date=date(2026, 6, 30),
                    start_time="09:00:00",
                    frames=100,
                    tr=3.0,
                )
            ],
        )

        start_time, end_time, dicom_count, _ = compute_session_times(session)

        self.assertEqual(start_time, datetime(2026, 6, 30, 9, 0, 0))
        self.assertEqual(end_time, datetime(2026, 6, 30, 9, 0, 0, 300000))
        self.assertEqual(dicom_count, 3)

    def test_refresh_cache_writes_scan_profile_from_compute_session_times(self) -> None:
        class FakeClient:
            def get_archive_sessions(self, start_date: str, end_date: str) -> list[dict[str, object]]:
                return [
                    {
                        "session_id": "SESSION6",
                        "subject_id": "SUBJ6",
                        "project_id": "PROJ6",
                        "date": "2026-06-30",
                        "state": "ARCHIVED",
                        "scans": [{"sequence_name": "T1", "dicom_count": 3}],
                    }
                ]

            def get_prearchive_sessions(self, start_date: str, end_date: str) -> list[dict[str, object]]:
                return []

        class FakeStore:
            def __init__(self) -> None:
                self.records: list[dict[str, object]] = []

            def has_changed(self, session_id: str, signature: str) -> bool:
                return True

            def mark_checked(self, session_id: str) -> None:
                return None

            def upsert(self, record: dict[str, object]) -> None:
                self.records.append(record)

        store = FakeStore()
        refresh_cache(client=FakeClient(), store=store, lookback_days=1)

        self.assertEqual(len(store.records), 1)
        self.assertIn("scan_profile", store.records[0])
        self.assertIsInstance(store.records[0]["scan_profile"], str)
        self.assertNotEqual(store.records[0]["scan_profile"], "")

    def test_extract_archive_session_handles_eattrs_like_values(self) -> None:
        class Attrs:
            def __init__(self, values: dict[str, object]) -> None:
                self._values = values

            def get(self, name: str, default: Optional[object] = None) -> Optional[object]:
                return self._values.get(name, default)

        class FakeRaw:
            def __init__(self) -> None:
                self.attrs = Attrs(
                    {
                        "subject_id": "SUBJ4",
                        "project_id": "PROJ4",
                        "date": "2026-06-29",
                    }
                )
                self.id = "SESSION4"

        record = extract_archive_session(FakeRaw())

        self.assertIsNotNone(record)
        self.assertEqual(record["subject_id"], "SUBJ4")
        self.assertEqual(record["project_id"], "PROJ4")
        self.assertEqual(record["session_id"], "SESSION4")
        self.assertEqual(record["date"], "2026-06-29")

    def test_extract_prearchive_session_handles_attrs_get_errors(self) -> None:
        class Attrs:
            def keys(self) -> list[str]:
                return []

            def get(self, name: str, default: Optional[object] = None) -> Optional[object]:
                raise IndexError("list index out of range")

        class FakeRaw:
            def __init__(self) -> None:
                self.attrs = Attrs()
                self.id = "SESSION5"

        record = extract_prearchive_session(FakeRaw())

        self.assertIsNotNone(record)
        self.assertEqual(record["session_id"], "SESSION5")
        self.assertEqual(record["subject_id"], "")
        self.assertEqual(record["project_id"], "")

    def test_fetch_prearchive_metadata_filters_by_uploaded_date(self) -> None:
        class FakeResponse:
            def __init__(self, payload: dict[str, object]) -> None:
                self._payload = payload

            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, object]:
                return self._payload

        class FakeSession:
            def __init__(self, payload: dict[str, object]) -> None:
                self.auth = None
                self._payload = payload

            def get(self, url: str, timeout: int = 30) -> FakeResponse:
                return FakeResponse(self._payload)

        payload = {
            "ResultSet": {
                "Result": [
                    {"subject": "SUBJ7", "project": "PROJ7", "scan_date": "2026-06-28", "uploaded": "2026-06-29 12:00:00"},
                    {"subject": "SUBJ8", "project": "PROJ8", "scan_date": "2026-06-30", "uploaded": "2025-06-01 00:00:00"},
                    {"subject": "SUBJ9", "project": "PROJ9", "scan_date": "2026-06-30", "uploaded": "2026-06-30 00:00:00"},
                ]
            }
        }

        client = XNATClient("https://example.test", lookback_days=365)

        with patch("xnat_audit.ingestion.client.requests", type("FakeRequests", (), {"Session": lambda: FakeSession(payload)})), patch.object(XNATClient, "_load_credentials", return_value=(None, None)):
            rows = client._fetch_prearchive_metadata("2026-06-01", "2026-06-30")

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["subject"], "SUBJ7")
        self.assertEqual(rows[1]["subject"], "SUBJ9")

    def test_build_prearchive_record_enriches_scans_and_resources(self) -> None:
        class FakeResponse:
            def __init__(self, payload: dict[str, object]) -> None:
                self._payload = payload

            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, object]:
                return self._payload

        class FakeSession:
            def __init__(self, payloads: dict[str, dict[str, object]]) -> None:
                self.auth = None
                self._payloads = payloads

            def get(self, url: str, timeout: int = 30) -> FakeResponse:
                if url.endswith("/scans?format=json"):
                    return FakeResponse(self._payloads["scans"])
                if url.endswith("/resources?format=json"):
                    return FakeResponse(self._payloads["resources"])
                raise AssertionError(f"Unexpected URL: {url}")

        payloads = {
            "scans": {
                "ResultSet": {
                    "Result": [
                        {"ID": "1", "series_description": "MPRAGE"},
                    ]
                }
            },
            "resources": {
                "ResultSet": {
                    "Result": [
                        {"cat_id": "1", "file_count": 12, "file_size": 1024},
                    ]
                }
            },
        }

        client = XNATClient("https://example.test", lookback_days=365)

        with patch("xnat_audit.ingestion.client.requests", type("FakeRequests", (), {"Session": lambda: FakeSession(payloads)})), patch.object(XNATClient, "_load_credentials", return_value=(None, None)):
            record = client._build_prearchive_record(
                {
                    "subject": "SUBJ10",
                    "project": "PROJ10",
                    "scan_date": "2026-06-30",
                    "scan_time": "09:00:00",
                    "uploaded": "2026-06-30 00:00:00",
                    "status": "READY",
                    "url": "https://example.test/data/prearchive/projects/PROJ10/20260630/SESSION10",
                }
            )

        self.assertIsNotNone(record)
        self.assertEqual(record["date"], "2026-06-30")
        self.assertEqual(len(record["scans"]), 1)
        self.assertEqual(record["scans"][0]["sequence_number"], "1")
        self.assertEqual(record["scans"][0]["series_description"], "MPRAGE")
        self.assertEqual(record["scans"][0]["dicom_count"], 12)

    def test_build_prearchive_record_uses_scan_date_time_fallback_when_enrichment_fails(self) -> None:
        class FakeResponse:
            def __init__(self, payload: dict[str, object]) -> None:
                self._payload = payload

            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, object]:
                return self._payload

        class FakeSession:
            def __init__(self, payload: dict[str, object]) -> None:
                self.auth = None
                self._payload = payload

            def get(self, url: str, timeout: int = 30) -> FakeResponse:
                raise RuntimeError("boom")

        client = XNATClient("https://example.test", lookback_days=365)

        with patch("xnat_audit.ingestion.client.requests", type("FakeRequests", (), {"Session": lambda: FakeSession({})})), patch.object(XNATClient, "_load_credentials", return_value=(None, None)):
            record = client._build_prearchive_record(
                {
                    "subject": "SUBJ11",
                    "project": "PROJ11",
                    "scan_date": "2026-06-30",
                    "scan_time": "09:00:00",
                    "uploaded": "2026-06-30 00:00:00",
                    "status": "READY",
                    "url": "https://example.test/data/prearchive/projects/PROJ11/20260630/SESSION11",
                }
            )

        self.assertIsNotNone(record)
        self.assertEqual(record["session_id"], "prearchive:SUBJ11:PROJ11:2026-06-30:09:00:00")
        self.assertEqual(len(record["scans"]), 1)
        self.assertEqual(record["scans"][0]["start_date"], "2026-06-30")
        self.assertEqual(record["scans"][0]["start_time"], "09:00:00")

    def test_get_archive_sessions_filters_before_expansion(self) -> None:
        class FakeSelector:
            def __init__(self, items: list[object]) -> None:
                self._items = items

            def experiments(self) -> list[object]:
                return self._items

            def projects(self) -> list[object]:
                return []

        class FakeExperiment:
            def __init__(self, session_id: str, date_value: str) -> None:
                self.id = session_id
                self.attrs = {"subject_id": "SUBJ", "project_id": "PROJ", "date": date_value}

        recent = FakeExperiment("SESSION_RECENT", "2026-06-29")
        old = FakeExperiment("SESSION_OLD", "2025-01-01")
        client = XNATClient("https://example.test", lookback_days=365)
        client.connect = lambda: type("Interface", (), {"select": FakeSelector([recent, old])})()  # type: ignore[assignment]

        records = client.get_archive_sessions("2026-01-01", "2026-06-30")

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["session_id"], "SESSION_RECENT")

    def test_get_archive_sessions_skips_project_fallback_when_direct_query_is_empty(self) -> None:
        class FakeProject:
            def __init__(self) -> None:
                self.experiments_calls = 0

            def experiments(self) -> list[object]:
                self.experiments_calls += 1
                return []

        class FakeSelector:
            def __init__(self, projects: list[FakeProject]) -> None:
                self._projects = projects

            def experiments(self) -> list[object]:
                return []

            def projects(self) -> list[FakeProject]:
                return self._projects

        projects = [FakeProject(), FakeProject(), FakeProject()]
        client = XNATClient("https://example.test", lookback_days=365)
        client.connect = lambda: type("Interface", (), {"select": FakeSelector(projects)})()  # type: ignore[assignment]

        records = client.get_archive_sessions("2026-01-01", "2026-06-30")

        self.assertEqual(records, [])
        self.assertTrue(all(project.experiments_calls == 0 for project in projects))


if __name__ == "__main__":
    unittest.main()
