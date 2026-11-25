#!/usr/bin/env python3
"""Install and exercise the hourly, per-user macOS LaunchAgent."""
import argparse
import hashlib
import json
import os
import plistlib
import sqlite3
import subprocess
import sys
import tempfile
import time
from contextlib import closing
from pathlib import Path

LABEL = "local.siri-recap-collector"
BASE = Path.home() / "Library/Application Support/SiriRecapCollector"
ARCHIVE = BASE / "recaps.sqlite3"
AGENT = Path.home() / "Library/LaunchAgents" / (LABEL + ".plist")
DOMAIN = f"gui/{os.getuid()}"
SERVICE = f"{DOMAIN}/{LABEL}"
CTL = "/bin/launchctl"
LEGACY_SCRIPT = "f8f258b8c21712da51a4960c441510b826172c7f37988e8efe77a6270b79e2c5"


def install_file(path, content, known_hash=None):
    if path.is_symlink():
        raise SystemExit(f"Refusing to overwrite symbolic link: {path}")
    if path.exists():
        old = path.read_bytes()
        if old == content:
            return
        if hashlib.sha256(old).hexdigest() != known_hash:
            raise SystemExit(f"Existing file differs: {path}. Review or move it before installing.")
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
        try:
            temporary.write(content)
            temporary.flush()
            os.replace(temporary.name, path)
        finally:
            Path(temporary.name).unlink(missing_ok=True)


def status():
    if not ARCHIVE.exists():
        return None, {}
    with closing(sqlite3.connect(ARCHIVE.as_uri() + "?mode=ro", uri=True, timeout=5)) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='collector_status'").fetchone():
            return None, {}
        row = db.execute("SELECT token,stats FROM collector_status WHERE slot=1").fetchone()
        return (row[0], json.loads(row[1])) if row else (None, {})


def job():
    return subprocess.run([CTL, "print", SERVICE], capture_output=True, text=True)


def wait_for_run(previous, elapsed=45):
    deadline = time.monotonic() + elapsed
    while time.monotonic() < deadline:
        token, stats = status()
        if token and token != previous:
            if stats.get("unreadable"):
                raise RuntimeError("Background run reported unreadable records.")
            print(json.dumps(stats), flush=True)
            return token
        time.sleep(0.5)
    raise RuntimeError(f"Background job wrote no new status. Check {BASE / 'errors.log'}.")


def main():
    if sys.platform != "darwin":
        raise SystemExit("Installation requires macOS.")
    os.umask(0o077)
    source = Path(__file__).resolve().with_name("collector.py")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-folder", type=Path, help="the authorized AgentSessionKit folder")
    args = parser.parse_args()
    location = ["--source-folder", str(args.source_folder.expanduser().absolute())] if args.source_folder else []
    # Check the invoking app's access before creating or changing a job.
    subprocess.run([sys.executable, "-B", str(source), *location], check=True)
    BASE.mkdir(mode=0o700, parents=True, exist_ok=True)
    AGENT.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    target = BASE / "collect.py"
    definition = {
        "Label": LABEL,
        "ProgramArguments": [sys.executable, "-B", str(target), *location, "--archive", str(ARCHIVE)],
        "RunAtLoad": True, "StartInterval": 3600, "ThrottleInterval": 1,
        "StandardOutPath": str(BASE / "runs.log"), "StandardErrorPath": str(BASE / "errors.log"),
    }
    legacy = dict(definition)
    legacy["ProgramArguments"] = [sys.executable, "-B", str(target), "--archive", str(ARCHIVE)]
    old_plist_hash = hashlib.sha256(plistlib.dumps(legacy)).hexdigest()
    previous_definition = AGENT.read_bytes() if AGENT.is_file() else None
    plist_bytes = plistlib.dumps(definition)
    install_file(AGENT, plist_bytes, old_plist_hash)
    install_file(target, source.read_bytes(), LEGACY_SCRIPT)
    # Preserve accessible recaps now, even if the separate background context fails.
    subprocess.run([sys.executable, "-B", str(target), *location, "--archive", str(ARCHIVE)], check=True)
    before, _ = status()
    loaded = job().returncode == 0
    subprocess.run([CTL, "enable", SERVICE], check=True)
    if loaded and previous_definition != plist_bytes:
        subprocess.run([CTL, "bootout", SERVICE], check=True)
        loaded = False
    if loaded:
        subprocess.run([CTL, "kickstart", SERVICE], check=True)
    else:
        subprocess.run([CTL, "bootstrap", DOMAIN, str(AGENT)], check=True)
    try:
        first = wait_for_run(before)
        for _ in range(20):
            if "state = running" not in job().stdout:
                break
            time.sleep(0.5)
        subprocess.run([CTL, "kickstart", SERVICE], check=True)
        wait_for_run(first)
    except (RuntimeError, subprocess.CalledProcessError):
        if not loaded:
            subprocess.run([CTL, "disable", SERVICE], check=False)
            subprocess.run([CTL, "bootout", SERVICE], check=False)
        raise
    print(f"Two background runs verified. Hourly archive: {ARCHIVE}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, sqlite3.Error, RuntimeError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))
