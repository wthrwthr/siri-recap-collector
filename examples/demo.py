"""Try a search and a source-backed lookup with invented recaps in memory."""
import importlib.util
import json
import sqlite3
from argparse import Namespace
from contextlib import closing
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / ".agents/skills/siri-recaps/scripts/query.py"
spec = importlib.util.spec_from_file_location("recap_query", SCRIPT)
query = importlib.util.module_from_spec(spec)
spec.loader.exec_module(query)


def main():
    samples = [
        ("demo-1", "2026-01-15T16:00:00+00:00", "Garden planning", "Bring seed packets to the next meeting."),
        ("demo-2", "2026-01-16T16:00:00+00:00", "Volunteer handoff", "Agreed to move Saturday setup to 9 AM. The welcome team will bring signs."),
    ]
    with closing(sqlite3.connect(":memory:")) as db:
        db.execute("CREATE TABLE recaps (id TEXT PRIMARY KEY, document TEXT NOT NULL)")
        for key, start, title, summary in samples:
            doc = {"id": key, "start_utc": start, "title": title, "summary": summary}
            db.execute("INSERT INTO recaps VALUES (?,?)", (key, json.dumps(doc)))
        matches = query.query(db, Namespace(command="search", term="Saturday setup", limit=5, since=None, through=None))
        print("Search for 'Saturday setup' in two fictional recaps")
        for match in matches["results"]:
            source = query.query(db, Namespace(command="show", id=match["id"]))
            print(f"{source['start_utc'][:10]} | {source['title']} | {source['id']}")
            print(source["text"].split("\n", 1)[-1])
        return 0 if len(matches["results"]) == 1 else 1


if __name__ == "__main__":
    raise SystemExit(main())
