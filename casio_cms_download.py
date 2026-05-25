#!/usr/bin/env python3
"""
CASIO MUSIC SPACE — bulk downloader for MIDI/MP3/PDF/TXT via
the public endpoint https://musicapp.casio.jp/dlmusicdata/dlmusicdata_android.php

The endpoint accepts a POST request whose entire body is the bare
"<file_id>.<ext>" string (no key=value, no URL encoding), and returns
the raw asset as application/force-download. Discovered by analyzing
jp.co.casio.CasioMusicCity (Casio Music Space) classes.dex —
specifically HTTPConnectionManager.HTTPrequestDL / HttpPostTask.

Usage:
    python3 casio_cms_download.py [--db cms_songs.db] [--out DIR]
                                  [--ext mid,mp3,pdf,txt]
                                  [--types SP,DP] [--workers 4]
                                  [--filter LIKE]

Examples:
    # Download every DP song's MIDI
    python3 casio_cms_download.py --types DP --ext mid

    # Download MIDI + PDF score for everything
    python3 casio_cms_download.py --ext mid,pdf

    # Limit to Beyer collection
    python3 casio_cms_download.py --filter "BY%" --ext mid,mp3,pdf,txt
"""
from __future__ import annotations

import argparse
import concurrent.futures
import sqlite3
import sys
import time
import urllib.request
from pathlib import Path

ENDPOINT = "https://musicapp.casio.jp/dlmusicdata/dlmusicdata_android.php"
DEFAULT_EXTS = ("mid",)
VALID_EXTS = ("mid", "mp3", "pdf", "txt")


def download_one(file_id: str, ext: str, out_dir: Path, *, timeout: float = 30.0) -> tuple[str, int, str]:
    payload = f"{file_id}.{ext}".encode("utf-8")
    req = urllib.request.Request(
        ENDPOINT,
        data=payload,
        method="POST",
        headers={
            "User-Agent": "Android",
            "Content-Length": str(len(payload)),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
    except Exception as e:
        return (file_id, 0, f"ERR {e.__class__.__name__}: {e}")

    if not body:
        return (file_id, 0, "empty")

    dst = out_dir / ext / f"{file_id}.{ext}"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(body)
    return (file_id, len(body), "ok")


def fetch_songs(db_path: Path, types: list[str], filter_like: str | None) -> list[tuple[str, str, str]]:
    conn = sqlite3.connect(str(db_path))
    placeholders = ",".join("?" * len(types))
    sql = (
        f"SELECT file_id, title_en, songs_collection FROM songs "
        f"WHERE data_type IN ({placeholders})"
    )
    params: list[str] = list(types)
    if filter_like:
        sql += " AND file_id LIKE ?"
        params.append(filter_like)
    sql += " ORDER BY file_id"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="assets/DB/cms_songs.db", help="cms_songs.db path")
    ap.add_argument("--out", default="cms_downloads", help="output directory")
    ap.add_argument("--ext", default="mid", help="comma-separated: mid,mp3,pdf,txt")
    ap.add_argument("--types", default="SP,DP", help="comma-separated data_type filter")
    ap.add_argument("--filter", default=None, help="SQL LIKE pattern on file_id, e.g. BY%%")
    ap.add_argument("--workers", type=int, default=4, help="parallel downloads")
    ap.add_argument("--skip-existing", action="store_true", help="skip when destination already exists")
    args = ap.parse_args()

    exts = [e.strip().lower() for e in args.ext.split(",") if e.strip()]
    for e in exts:
        if e not in VALID_EXTS:
            print(f"invalid extension: {e}", file=sys.stderr)
            return 2

    types = [t.strip() for t in args.types.split(",") if t.strip()]
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"db not found: {db_path}", file=sys.stderr)
        return 2

    songs = fetch_songs(db_path, types, args.filter)
    if not songs:
        print("no matching songs in DB")
        return 0

    print(f"target: {len(songs)} songs × {len(exts)} ext = {len(songs)*len(exts)} files")
    print(f"output: {out_dir.resolve()}")

    jobs: list[tuple[str, str]] = []
    for file_id, _title, _coll in songs:
        for ext in exts:
            if args.skip_existing and (out_dir / ext / f"{file_id}.{ext}").exists():
                continue
            jobs.append((file_id, ext))

    if not jobs:
        print("nothing to do (all files already exist)")
        return 0

    ok = empty = err = 0
    started = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(download_one, fid, ext, out_dir): (fid, ext) for fid, ext in jobs}
        for i, fut in enumerate(concurrent.futures.as_completed(futs), 1):
            fid, ext = futs[fut]
            file_id, size, status = fut.result()
            if status == "ok":
                ok += 1
                tag = "OK "
            elif status == "empty":
                empty += 1
                tag = "EMP"
            else:
                err += 1
                tag = "ERR"
            print(f"[{i:4d}/{len(jobs)}] {tag} {size:>9d}  {file_id}.{ext}  {status if status != 'ok' else ''}")

    elapsed = time.monotonic() - started
    print(f"\ndone in {elapsed:.1f}s: ok={ok} empty={empty} err={err}")
    return 0 if err == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
