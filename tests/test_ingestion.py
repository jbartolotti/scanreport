import tempfile
import unittest
from datetime import date
from pathlib import Path

from xnat_audit.ingestion.dicom_times import compute_session_times, compute_signature
from xnat_audit.models.enums import SessionOrigin, SessionState
from xnat_audit.models.scan import Scan
from xnat_audit.models.session import Session
from xnat_audit.storage.sqlite_store import SessionTimeStore


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

        start_time, end_time, dicom_count = compute_session_times(session)
        self.assertGreaterEqual(dicom_count, 1)
        self.assertLessEqual(start_time, end_time)


if __name__ == "__main__":
    unittest.main()
