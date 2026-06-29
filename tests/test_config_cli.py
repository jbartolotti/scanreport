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


if __name__ == "__main__":
    unittest.main()
