#!/usr/bin/env python3
"""Read the local Siri Recap Collector archive. No network or writes."""
import argparse
import heapq
import json
import sqlite3
import sys
from contextlib import closing
from datetime import date, datetime
from pathlib import Path

DEFAULT_ARCHIVE = Path.home() / "Library/Application Support/SiriRecapCollector/recaps.sqlite3"
MAX_TEXT = 10000


def parts(doc):
    for field in ("title", "summary"):
        value = doc.get(field)
        if isinstance(value, str) and value:
            yield value
    for section in doc.get("sections") or []:
        if isinstance(section, dict):
            heading = section.get("title")
            if isinstance(heading, str) and heading:
                yield heading
            yield from (v for v in section.get("keyPoints") or [] if isinstance(v, str))
    yield from (v for v in doc.get("keypoints") or [] if isinstance(v, str))


def load_doc(raw):
    doc = json.loads(raw)
    if not isinstance(doc, dict) or not isinstance(doc.get("title"), str):
        raise ValueError("invalid recap document")
    when = datetime.fromisoformat(doc["start_utc"].replace("Z", "+00:00"))
    if when.tzinfo is None:
        raise ValueError("recap has no time zone")
    return doc, when


def query(db, args):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='recaps'").fetchone():
        raise ValueError("Archive is uninitialized. Run a successful collection first.")
    if args.command == "status":
        count, first, last = db.execute("""
            SELECT count(*), min(start), max(start) FROM (
                SELECT CASE WHEN json_valid(document) THEN json_extract(document, '$.start_utc') END AS start
                FROM recaps
            )
        """).fetchone()
        return {"count": count, "first_utc": first, "last_utc": last}
    if args.command == "show":
        row = db.execute("SELECT document FROM recaps WHERE id=?", (args.id,)).fetchone()
        if row is None:
            raise ValueError("Capture ID was not found in this archive.")
        doc, _ = load_doc(row[0])
        body = "\n".join(dict.fromkeys(parts(doc)))
        return {"id": args.id, "start_utc": doc["start_utc"], "title": doc["title"][:300],
                "text": body[:MAX_TEXT], "truncated": len(body) > MAX_TEXT}

    term = getattr(args, "term", "").casefold()
    skipped = 0

    def matches():
        nonlocal skipped
        for identifier, raw in db.execute("SELECT id, document FROM recaps"):
            try:
                doc, when = load_doc(raw)
                day = when.astimezone().date()
                if (args.since and day < args.since) or (args.through and day > args.through):
                    continue
                if term and not any(term in part.casefold() for part in parts(doc)):
                    continue
                yield when, identifier, {"id": identifier, "start_utc": doc["start_utc"], "title": doc["title"][:300]}
            except (TypeError, KeyError, ValueError, AttributeError, OverflowError):
                skipped += 1

    selected = heapq.nlargest(args.limit, matches(), key=lambda item: item[:2])
    return {"results": [item[2] for item in selected], "skipped_invalid": skipped}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="report archive count and UTC bounds")
    commands.add_parser("show", help="read one matching record").add_argument("id")
    for name in ("recent", "search"):
        cmd = commands.add_parser(name)
        if name == "search":
            cmd.add_argument("term", help="literal, case-insensitive phrase")
        cmd.add_argument("--from", dest="since", type=date.fromisoformat, metavar="YYYY-MM-DD")
        cmd.add_argument("--through", type=date.fromisoformat, metavar="YYYY-MM-DD")
        cmd.add_argument("--limit", type=int, choices=range(1, 21), default=5, metavar="1..20")
    args = parser.parse_args(argv)
    if args.command in ("recent", "search"):
        if args.since and args.through and args.since > args.through:
            parser.error("--from must be on or before --through")
        if args.command == "search" and not args.term.strip():
            parser.error("enter a search phrase or use recent")
    path = args.archive.expanduser().resolve()
    try:
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=3)) as db:
            db.execute("PRAGMA query_only=ON")
            print(json.dumps(query(db, args), ensure_ascii=False))
    except (OSError, sqlite3.Error, ValueError, KeyError, TypeError, AttributeError, OverflowError) as err:
        print(f"Could not read the recap archive: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
