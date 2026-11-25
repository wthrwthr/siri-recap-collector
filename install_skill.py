#!/usr/bin/env python3
"""Install the bundled Siri Recaps skill for this Mac user."""
import argparse
import shutil
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

NAME = "siri-recaps"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.home() / ".agents/skills",
                        help="skill discovery directory (default: ~/.agents/skills)")
    args = parser.parse_args()
    source = Path(__file__).resolve().parent / ".agents/skills" / NAME
    root = args.root.expanduser().resolve()
    dest = root / NAME
    files = (Path("SKILL.md"), Path("scripts/query.py"))
    if not all((source / f).is_file() for f in files):
        sys.exit("Incomplete checkout. Download the repository with its .agents directory.")
    if dest.exists() or dest.is_symlink():
        if dest.is_dir() and all((dest / f).is_file() and (dest / f).read_bytes() == (source / f).read_bytes() for f in files):
            print(f"Already installed: {dest}")
            return
        sys.exit(f"An existing skill differs at {dest}. Review it before replacing it.")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    with TemporaryDirectory(dir=root) as tmp:
        staged = Path(tmp) / NAME
        for f in files:
            (staged / f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / f, staged / f)
        staged.rename(dest)
    print(f"Installed: {dest}")


if __name__ == "__main__":
    try:
        main()
    except OSError as exc:
        sys.exit(str(exc))
