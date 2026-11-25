#!/usr/bin/env python3
"""Archive Siri Recaps from the signed-in user's synced Mac store."""
import argparse
import base64
import json
import os
import sqlite3
import sys
import time
import uuid
from collections import Counter
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)
BASE = Path.home() / "Library/Daemon Containers"
DEFAULT_ARCHIVE = Path.home() / "Library/Application Support/SiriRecapCollector/recaps.sqlite3"
SQL = """
SELECT COALESCE(s.ZLASTMODIFIEDDATE, 0), COALESCE(a.ZVERSIONNUMBER, 0), a.ZCONTENTDATA
FROM ZAGENTSESSIONRECORDENTITY AS s
JOIN ZARTIFACTENTITY AS a ON a.ZSESSION = s.Z_PK
WHERE s.ZSOURCEBUNDLEID = 'com.apple.MindPalace'
  AND a.ZCONTENTTYPE = 'com.apple.mindpalace.capture'
ORDER BY s.ZLASTMODIFIEDDATE, a.ZVERSIONNUMBER, a.Z_PK
"""


def decode(blob):
    if not isinstance(blob, bytes) or blob[:1] != b"\x01":
        raise ValueError("unrecognized capture format")
    wrapper = json.loads(blob[1:])
    payload = base64.b64decode(wrapper["data"]["_0"], validate=True)
    data = json.loads(payload)
    if not isinstance(data, dict) or not isinstance(data.get("resultType"), str):
        raise ValueError("missing result type")
    if data["resultType"] != "success":
        return None
    if not all(isinstance(data.get(k), str) for k in ("identifier", "title", "summary")):
        raise ValueError("missing capture identifier or recap text")
    capture_id = str(uuid.UUID(data["identifier"]))
    interval = data["captureInterval"]
    start = APPLE_EPOCH + timedelta(seconds=interval["start"])
    sections = data.get("keypointSections", [])
    points = data.get("keypoints", [])
    if not isinstance(sections, list) or not isinstance(points, list):
        raise ValueError("unrecognized recap sections")
    return {
        "id": capture_id,
        "start_utc": start.isoformat(),
        "duration_seconds": interval["duration"],
        "title": data["title"],
        "summary": data["summary"],
        "sections": sections,
        "keypoints": points,
    }


def candidates(source_folder=None):
    found = False
    if source_folder is None:
        paths = (item / "Data/AgentSessionKit/AgentSessionStore.sqlite" for item in sorted(BASE.iterdir()))
    else:
        paths = (source_folder.expanduser().absolute() / "AgentSessionStore.sqlite",)
    for path in paths:
        try:
            path.stat()
        except FileNotFoundError:
            continue
        found = True
        if Path(str(path) + "-wal").exists() and not Path(str(path) + "-shm").exists():
            raise RuntimeError("Live source has no shared-memory sidecar. Try again after Siri syncs.")
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)) as source:
            source.execute("PRAGMA query_only=ON")
            yield from source.execute(SQL)
    if not found:
        raise RuntimeError("No readable AgentSessionKit store was found.")


def ingest(archive, rows):
    records = {}
    stats = Counter()
    for modified, version, blob in rows:
        stats["candidates"] += 1
        if not blob:
            stats["pending"] += 1
            continue
        try:
            record = decode(blob)
        except (ValueError, TypeError, KeyError, IndexError, OverflowError):
            stats["unreadable"] += 1
            continue
        if record is None:
            stats["other_results"] += 1
            continue
        identifier = record["id"]
        revision = (modified, version)
        if identifier not in records or revision >= records[identifier][0]:
            records[identifier] = (revision, json.dumps(record, ensure_ascii=False, sort_keys=True))

    with archive:
        archive.execute("BEGIN IMMEDIATE")
        archive.execute("CREATE TABLE IF NOT EXISTS recaps (id TEXT PRIMARY KEY, document TEXT NOT NULL)")
        archive.execute("CREATE TABLE IF NOT EXISTS recap_revisions (id TEXT PRIMARY KEY, modified REAL, version INTEGER)")
        for identifier, (revision, document) in records.items():
            prior = archive.execute(
                "SELECT r.document, v.modified, v.version FROM recaps r "
                "LEFT JOIN recap_revisions v ON r.id=v.id WHERE r.id=?", (identifier,)
            ).fetchone()
            if prior and prior[1] is not None and revision < prior[1:]:
                stats["older"] += 1
                continue
            if prior and prior[0] == document:
                stats["unchanged"] += 1
            else:
                archive.execute(
                    "INSERT INTO recaps VALUES(?,?) ON CONFLICT(id) DO UPDATE SET document=excluded.document",
                    (identifier, document),
                )
                stats["updated" if prior else "inserted"] += 1
            if not prior or prior[1:] != revision:
                archive.execute("INSERT OR REPLACE INTO recap_revisions VALUES(?,?,?)", (identifier, *revision))
        stats["archived"] = archive.execute("SELECT COUNT(*) FROM recaps").fetchone()[0]
        archive.execute("CREATE TABLE IF NOT EXISTS collector_status (slot INTEGER PRIMARY KEY, token TEXT NOT NULL, stats TEXT NOT NULL)")
        archive.execute("INSERT OR REPLACE INTO collector_status VALUES(1,?,?)", (str(uuid.uuid4()), json.dumps(stats)))
    return dict(sorted(stats.items()))


def collect(archive, source_folder=None):
    return ingest(archive, candidates(source_folder))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, help="create or update a local SQLite archive")
    parser.add_argument("--source-folder", type=Path, help="the AgentSessionKit folder selected in macOS Privacy & Security")
    parser.add_argument("--watch", action="store_true", help="collect now and then hourly while this process runs")
    args = parser.parse_args()
    os.umask(0o077)
    path = args.archive.expanduser() if args.archive else (DEFAULT_ARCHIVE if args.watch else None)
    if path:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with closing(sqlite3.connect(path or ":memory:", timeout=30)) as archive:
        while True:
            stats = collect(archive, args.source_folder)
            print(json.dumps(stats), flush=True)
            if not path:
                print(json.dumps(collect(archive, args.source_folder)), flush=True)
            if stats.get("unreadable"):
                return 2
            if not args.watch:
                return 0
            time.sleep(3600)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except PermissionError as error:
        sys.exit(f"Access denied by macOS: {error.filename or 'local file'}. Check access for this execution context.")
    except (OSError, sqlite3.Error, RuntimeError) as error:
        sys.exit(f"Collection failed: {error}")
    except KeyboardInterrupt:
        sys.exit(130)
