"""Isolated tests for the archive reader and local skill installation."""
import importlib.util
import json
import sqlite3
import subprocess
import sys
import unittest
from argparse import Namespace
from contextlib import closing
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / ".agents/skills/siri-recaps/scripts/query.py"
spec = importlib.util.spec_from_file_location("recap_query", SCRIPT)
reader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reader)


def run(db, command, **kwargs):
    options = {"since": None, "through": None, "limit": 5}
    options.update(kwargs)
    return reader.query(db, Namespace(command=command, **options))


class QueryTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.db.execute("CREATE TABLE recaps (id TEXT PRIMARY KEY, document TEXT NOT NULL)")
        for day in (10, 11, 12):
            doc = {"title": f"Example {day}", "start_utc": f"2026-01-{day}T12:00:00+00:00",
                   "summary": "Synthetic summary only", "sections": [{"title": "Plan", "keyPoints": ["Ship at 90%_ready"]}],
                   "keypoints": ["Example point"]}
            self.db.execute("INSERT INTO recaps VALUES(?,?)", (str(day), json.dumps(doc)))

    def test_status_has_counts_and_bounds_only(self):
        status = run(self.db, "status")
        self.assertEqual(set(status), {"count", "first_utc", "last_utc"})
        self.assertEqual(status["count"], 3)
        self.assertIn("01-10", status["first_utc"])

    def test_search_literal_and_limits(self):
        result = run(self.db, "search", term="90%_READY", limit=2)["results"]
        self.assertEqual([r["id"] for r in result], ["12", "11"])
        self.assertEqual(set(result[0]), {"id", "start_utc", "title"})
        self.assertFalse(run(self.db, "search", term="90Xready")["results"])
        self.assertFalse(run(self.db, "search", term="' OR 1=1 --")["results"])

    def test_dates_and_invalid_documents(self):
        self.db.execute("INSERT INTO recaps VALUES('bad', 'broken')")
        res = run(self.db, "recent", since=date(2026, 1, 9), through=date(2026, 1, 13))
        self.assertEqual(len(res["results"]), 3)
        self.assertEqual(res["skipped_invalid"], 1)
        self.assertFalse(run(self.db, "recent", since=date(2026, 2, 1))["results"])

    def test_show_is_bounded_and_exact(self):
        huge = {"title": "Synthetic long recap", "summary": "x" * 11000, "start_utc": "2026-01-01T12:00:00+00:00"}
        self.db.execute("INSERT INTO recaps VALUES('long', ?)", (json.dumps(huge),))
        result = run(self.db, "show", id="long")
        self.assertTrue(result["truncated"])
        self.assertEqual(len(result["text"]), reader.MAX_TEXT)
        with self.assertRaises(ValueError):
            run(self.db, "show", id="' OR 1=1 --")

    def test_uninitialized_and_empty(self):
        with closing(sqlite3.connect(":memory:")) as empty:
            with self.assertRaisesRegex(ValueError, "uninitialized"):
                run(empty, "status")
        self.db.execute("DELETE FROM recaps")
        self.assertEqual(run(self.db, "status"), {"count": 0, "first_utc": None, "last_utc": None})


class InstallTests(unittest.TestCase):
    def test_install_and_query(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            install = [sys.executable, "-B", str(ROOT / "install_skill.py"), "--root", str(root / "skills")]
            subprocess.run(install, check=True, capture_output=True)
            self.assertIn("Already installed", subprocess.check_output(install, text=True))
            folder = root / "skills/siri-recaps"
            self.assertEqual((folder / "SKILL.md").read_bytes(), (SCRIPT.parent.parent / "SKILL.md").read_bytes())
            archive = root / "archive.sqlite3"
            cmd = [sys.executable, "-B", str(folder / "scripts/query.py"), "--archive", str(archive), "status"]
            self.assertNotEqual(subprocess.run(cmd, capture_output=True).returncode, 0)
            self.assertFalse(archive.exists())
            with closing(sqlite3.connect(archive)) as db:
                db.execute("CREATE TABLE recaps (id TEXT PRIMARY KEY, document TEXT NOT NULL)")
                db.commit()
            self.assertEqual(json.loads(subprocess.check_output(cmd))["count"], 0)
            (folder / "SKILL.md").write_text("user edit")
            self.assertNotEqual(subprocess.run(install, capture_output=True).returncode, 0)
            self.assertEqual((folder / "SKILL.md").read_text(), "user edit")


if __name__ == "__main__":
    unittest.main()
