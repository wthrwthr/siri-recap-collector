"""Synthetic source and archive. These tests never open a user's Siri database."""
import base64
import json
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import collector

IDENTIFIER = "12345678-1234-4567-89ab-123456789abc"
BUNDLE = "com.apple.MindPalace"
TYPE = "com.apple.mindpalace.capture"


def envelope(payload):
    encoded = base64.b64encode(json.dumps(payload).encode()).decode("ascii")
    return b"\x01" + json.dumps({"data": {"_0": encoded}}).encode()


def capture(summary="An invented summary.", **overrides):
    data = {
        "identifier": IDENTIFIER, "resultType": "success", "title": "Test recap",
        "summary": summary, "captureInterval": {"start": 0, "duration": 60},
        "keypointSections": [{"title": "Example", "keyPoints": ["An invented point."]}],
        "keypoints": ["An invented point."],
    }
    data.update(overrides)
    return envelope(data)


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.source = sqlite3.connect(":memory:")
        self.archive = sqlite3.connect(":memory:")
        self.addCleanup(self.source.close)
        self.addCleanup(self.archive.close)
        self.source.executescript("""
            CREATE TABLE ZAGENTSESSIONRECORDENTITY (
                Z_PK INTEGER PRIMARY KEY, ZSOURCEBUNDLEID TEXT, ZLASTMODIFIEDDATE REAL);
            CREATE TABLE ZARTIFACTENTITY (
                Z_PK INTEGER PRIMARY KEY, ZSESSION INTEGER, ZCONTENTTYPE TEXT,
                ZCONTENTDATA BLOB, ZVERSIONNUMBER INTEGER);
        """)

    def add(self, blob, bundle=BUNDLE, content_type=TYPE):
        with self.source:
            session = self.source.execute(
                "INSERT INTO ZAGENTSESSIONRECORDENTITY (ZSOURCEBUNDLEID, ZLASTMODIFIEDDATE) VALUES (?, 1)",
                (bundle,),
            ).lastrowid
            self.source.execute(
                "INSERT INTO ZARTIFACTENTITY (ZSESSION, ZCONTENTTYPE, ZCONTENTDATA, ZVERSIONNUMBER) VALUES (?, ?, ?, 1)",
                (session, content_type, blob),
            )

    def sync(self):
        with patch.object(collector, "candidates", return_value=self.source.execute(collector.SQL)):
            return collector.collect(self.archive)

    def document(self):
        row = self.archive.execute("SELECT document FROM recaps WHERE id=?", (IDENTIFIER,)).fetchone()
        return json.loads(row[0])

    def test_archive_lifecycle(self):
        self.add(capture())
        self.assertEqual(self.sync()["inserted"], 1)
        doc = self.document()
        self.assertEqual(doc["start_utc"], "2001-01-01T00:00:00+00:00")
        self.assertEqual(doc["sections"][0]["keyPoints"], doc["keypoints"])
        self.assertEqual(self.sync()["unchanged"], 1)
        with self.source:
            self.source.execute("UPDATE ZARTIFACTENTITY SET ZCONTENTDATA=?", (capture("Edited summary."),))
        self.assertEqual(self.sync()["updated"], 1)
        with self.source:
            self.source.execute("DELETE FROM ZARTIFACTENTITY")
        self.assertEqual(self.sync()["archived"], 1)
        self.assertEqual(self.document()["summary"], "Edited summary.")

    def test_filter_and_malformed_records(self):
        self.add(capture(), bundle="example.unrelated")
        self.add(capture(), content_type="example.attachment")
        self.add(None)
        self.add(b'\x01{"data":{"_0":"%%%"}}')
        self.add(envelope([]))
        self.add(capture(identifier=42))
        self.add(capture(resultType="other"))
        self.add(capture())
        stats = self.sync()
        self.assertEqual(stats["candidates"], 6)
        self.assertEqual(stats["unreadable"], 3)
        self.assertEqual(stats["pending"], 1)
        self.assertEqual(stats["other_results"], 1)
        self.assertEqual(stats["archived"], 1)

    def test_older_copy_does_not_replace_newer(self):
        new = (20, 1, capture("Newer"))
        old = (10, 2, capture("Older"))
        collector.ingest(self.archive, [new, old])
        self.assertEqual(self.document()["summary"], "Newer")
        self.assertEqual(collector.ingest(self.archive, [old])["older"], 1)
        self.assertEqual(self.document()["summary"], "Newer")

    def test_selected_folder_does_not_enumerate_parent(self):
        source = Mock()
        source.execute.side_effect = [None, [(1, 1, capture())]]
        directory = Path("/synthetic/AgentSessionKit")
        with patch.object(collector, "BASE") as base, patch.object(Path, "stat"), \
             patch.object(Path, "exists", return_value=False), \
             patch.object(collector.sqlite3, "connect", return_value=source) as connect:
            rows = list(collector.candidates(directory))
        base.iterdir.assert_not_called()
        self.assertEqual(len(rows), 1)
        uri = (directory / "AgentSessionStore.sqlite").as_uri() + "?mode=ro"
        connect.assert_called_once_with(uri, uri=True, timeout=5)
        source.close.assert_called_once()

    def test_empty_scan_records_fresh_status(self):
        self.assertEqual(self.sync()["archived"], 0)
        token = self.archive.execute("SELECT token FROM collector_status").fetchone()[0]
        self.sync()
        self.assertNotEqual(token, self.archive.execute("SELECT token FROM collector_status").fetchone()[0])


if __name__ == "__main__":
    unittest.main()
