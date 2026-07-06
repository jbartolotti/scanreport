import io
import json
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from xnat_audit.cli.main import build_parser, main
from xnat_audit.config.config import load_settings
from xnat_audit.reporting.report import generate_report
from xnat_audit.storage.sqlite_store import SessionTimeStore


class ConfigCliTests(unittest.TestCase):
    def test_load_settings_from_json_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "xnat_url": "https://example.test",
                        "sqlite_db_path": "./tmp/cache.db",
                        "lookback_days": 14,
                        "netrc_host": "example",
                        "date_window_days": 3,
                    }
                ),
                encoding="utf-8",
            )

            settings = load_settings(config_path)

            self.assertEqual(settings.xnat_url, "https://example.test")
            self.assertEqual(settings.sqlite_db_path, "./tmp/cache.db")
            self.assertEqual(settings.lookback_days, 14)
            self.assertEqual(settings.netrc_host, "example")
            self.assertEqual(settings.date_window_days, 3)

    def test_main_uses_current_date_when_not_supplied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.json"
            config_path.write_text(json.dumps({"xnat_url": "https://example.test"}), encoding="utf-8")

            previous_cwd = os.getcwd()
            try:
                os.chdir(tmp_dir)
                with patch("sys.stdout", new_callable=io.StringIO) as stdout:
                    exit_code = main([])
            finally:
                os.chdir(previous_cwd)

            self.assertEqual(exit_code, 0)
            self.assertIn(date.today().strftime("%Y-%m-%d"), stdout.getvalue())

    def test_main_initializes_sqlite_cache_when_config_supplied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.json"
            config_path.write_text(
                json.dumps({"xnat_url": "https://example.test", "sqlite_db_path": str(Path(tmp_dir) / "cache" / "session_times.db")}),
                encoding="utf-8",
            )

            with patch("sys.stdout", new_callable=io.StringIO) as stdout:
                exit_code = main([str(config_path)])

            self.assertEqual(exit_code, 0)
            self.assertTrue(Path(tmp_dir, "cache", "session_times.db").exists())
            self.assertIn("Initializing SQLite cache", stdout.getvalue())

    def test_build_parser_accepts_verbose_flag(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--verbose", "config.json"])

        self.assertTrue(args.verbose)

    def test_build_parser_accepts_refresh_and_report_commands(self) -> None:
        parser = build_parser()
        refresh_args = parser.parse_args(["refresh", "config.json"])
        report_args = parser.parse_args(["report", "--date", "2026-06-29"])

        self.assertEqual(refresh_args.command, "refresh")
        self.assertEqual(report_args.command, "report")
        self.assertEqual(report_args.report_date, "2026-06-29")

    def test_generate_report_reads_from_sqlite_registry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "registry.db")
            store = SessionTimeStore(db_path)
            store.upsert(
                {
                    "session_id": "S1",
                    "project_id": "P1",
                    "state": "ARCHIVED",
                    "start_time": "2026-06-29T10:00:00+00:00",
                    "end_time": "2026-06-29T11:00:00+00:00",
                    "dicom_count": 3,
                    "scan_profile": "t1",
                    "signature": "sig1",
                    "last_checked": "2026-06-29T00:00:00+00:00",
                }
            )
            store.close()

            reopened = SessionTimeStore(db_path)
            report = generate_report(store=reopened, report_date=date(2026, 6, 29))
            reopened.close()

            self.assertEqual(report["session_count"], 1)
            self.assertEqual(report["sessions"][0]["session_id"], "S1")

    def test_main_generates_weekly_html_report_from_sqlite_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "registry.db")
            config_path = Path(tmp_dir) / "config.json"
            config_path.write_text(json.dumps({"sqlite_db_path": db_path}), encoding="utf-8")

            previous_cwd = os.getcwd()
            try:
                os.chdir(tmp_dir)
                store = SessionTimeStore(db_path)
                store.upsert(
                    {
                        "session_id": "S2",
                        "project_id": "P2",
                        "state": "PREARCHIVE",
                        "start_time": "2026-06-29T09:00:00+00:00",
                        "end_time": None,
                        "dicom_count": 7,
                        "scan_profile": "t2",
                        "signature": "sig2",
                        "last_checked": "2026-06-29T00:00:00+00:00",
                    }
                )
                store.close()

                with patch("sys.stdout", new_callable=io.StringIO) as stdout:
                    exit_code = main(["report", "--week", "2026-06-29", str(config_path)])
            finally:
                os.chdir(previous_cwd)

            self.assertEqual(exit_code, 0)
            report_path = Path(tmp_dir) / "report.html"
            self.assertTrue(report_path.exists())
            html = report_path.read_text(encoding="utf-8")
            self.assertIn("Weekly Report", html)
            self.assertIn("P2", html)
            self.assertIn("S2", html)
            self.assertIn("PREARCHIVE", html)
            self.assertIn("report-week", html)


if __name__ == "__main__":
    unittest.main()
