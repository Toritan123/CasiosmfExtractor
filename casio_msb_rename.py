#!/usr/bin/env python3
"""
MobileSongBank — rename downloaded MIDI files to "<title> - <artist>.mid"
using SongDB.sqlite3.

Reads <src>/*.mid (named <file_name>.mid as produced by casio_msb_download.py)
and copies them to <dst>/ with human-readable filenames.

Usage:
    python3 casio_msb_rename.py [--src DIR] [--dst DIR] [--db PATH]
                                [--move] [--format STR]

Examples:
    python3 casio_msb_rename.py \
        --src msb_downloads/mid \
        --dst msb_downloads/mid_named \
        --db /path/to/SongDB.sqlite3
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from pathlib import Path

# Characters not allowed in filenames on common filesystems.
_FS_UNSAFE = '/\\:*?"<>|'
_FS_TABLE = str.maketrans({c: "_" for c in _FS_UNSAFE})


def sanitize(name: str) -> str:
    # Translate unsafe chars, strip control chars, collapse whitespace,
    # trim trailing dots/spaces (problematic on Windows).
    name = name.translate(_FS_TABLE)
    name = "".join(c for c in name if c >= " ")
    name = " ".join(name.split())
    return name.rstrip(" .") or "_"


def load_map(db_path: Path, fmt: str) -> dict[str, str]:
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute("SELECT file_name, title, artist FROM songs").fetchall()
    conn.close()

    out: dict[str, str] = {}
    for file_name, title, artist in rows:
        title = (title or "").strip()
        artist = (artist or "").strip()
        if not title:
            continue
        if artist in ("", "-"):
            base = title
        else:
            base = fmt.format(title=title, artist=artist)
        out[file_name] = sanitize(base)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--src", default="msb_downloads/mid", help="folder containing <file_name>.mid")
    ap.add_argument("--dst", default="msb_downloads/mid_named", help="output folder")
    ap.add_argument("--db", default="SongDB.sqlite3", help="SongDB.sqlite3 path")
    ap.add_argument(
        "--format",
        default="{title} - {artist}",
        help='filename pattern (default: "{title} - {artist}")',
    )
    ap.add_argument("--move", action="store_true", help="move instead of copy")
    args = ap.parse_args()

    src = Path(args.src)
    dst = Path(args.dst)
    db = Path(args.db)

    if not src.is_dir():
        print(f"src not found: {src}", file=sys.stderr)
        return 2
    if not db.is_file():
        print(f"db not found: {db}", file=sys.stderr)
        return 2

    name_map = load_map(db, args.format)
    if not name_map:
        print("empty name map; check --db", file=sys.stderr)
        return 2

    dst.mkdir(parents=True, exist_ok=True)

    used: set[str] = set()
    ok = miss = 0
    src_files = sorted(src.glob("*.mid"))
    for f in src_files:
        file_name = f.stem
        title = name_map.get(file_name)
        if not title:
            print(f"  MISS  {f.name} (not in DB)")
            miss += 1
            continue

        # Dedup duplicates with " (2)", " (3)", ...
        candidate = f"{title}.mid"
        n = 2
        while candidate in used:
            candidate = f"{title} ({n}).mid"
            n += 1
        used.add(candidate)

        out_path = dst / candidate
        if args.move:
            shutil.move(str(f), str(out_path))
        else:
            shutil.copy2(str(f), str(out_path))
        ok += 1

    print(f"\ndone: {ok} renamed, {miss} missing in DB (of {len(src_files)} inputs)")
    print(f"output: {dst.resolve()}")
    return 0 if miss == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
