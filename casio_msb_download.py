#!/usr/bin/env python3
"""
MobileSongBank — bulk downloader for追加ダウンロード曲 (IAP songs).

Hits https://mobilesongbank.com/dlfprcheck/dlfortrial.php (no auth required),
which returns the full archive (LHA lh5 for .lhc, ZIP for .zip).
Discovered by analyzing jp.co.casio.MobileSongBank classes2.dex —
HTTPConnectionManager.HttpPostTask.

POST body format (application/x-www-form-urlencoded):
    filename=<file_name>.<lhc|zip>

.lhc archives contain a single <file_name>.mid.
.zip archives contain <file_name>.mid + .cmf + .fmc (finger guide).

Usage:
    python3 casio_msb_download.py [--db SongDB.sqlite3] [--out DIR]
                                  [--filter LIKE] [--workers 4]
                                  [--include-internal] [--no-extract]
                                  [--skip-existing]

Examples:
    # All 709 IAP songs (default: skip the 165 bundled songs)
    python3 casio_msb_download.py --db SongDB.sqlite3 --workers 8

    # Just one pack
    python3 casio_msb_download.py --filter "001AC%"
"""
from __future__ import annotations

import argparse
import concurrent.futures
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

ENDPOINT_LHC = "https://mobilesongbank.com/dlfprcheck/dlfortrial.php"
ENDPOINT_ZIP = "https://mobilesongbank.com/dlfprcheck/dlfortrialzip.php"


def download_one(
    file_name: str,
    compress_type: str,
    out_dir: Path,
    *,
    timeout: float = 30.0,
    skip_existing: bool = False,
) -> tuple[str, int, str]:
    if compress_type == "lhc":
        endpoint = ENDPOINT_LHC
        ext = "lhc"
    elif compress_type == "zip":
        endpoint = ENDPOINT_ZIP
        ext = "zip"
    else:
        return (file_name, 0, f"skip unknown compress_type={compress_type}")

    raw_dir = out_dir / "raw"
    dst = raw_dir / f"{file_name}.{ext}"
    if skip_existing and dst.exists() and dst.stat().st_size > 0:
        return (file_name, dst.stat().st_size, "cached")

    payload = urllib.parse.urlencode({"filename": f"{file_name}.{ext}"}).encode()
    req = urllib.request.Request(
        endpoint,
        data=payload,
        method="POST",
        headers={
            "User-Agent": "Android",
            "Content-Type": "application/x-www-form-urlencoded",
            "Content-Length": str(len(payload)),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
    except Exception as e:
        return (file_name, 0, f"ERR {e.__class__.__name__}: {e}")

    if not body:
        return (file_name, 0, "empty")

    # Sanity check the magic bytes so HTML error pages aren't saved as data.
    if ext == "lhc" and not (len(body) > 6 and body[2:6] == b"-lh5"):
        return (file_name, len(body), "ERR not LHA")
    if ext == "zip" and not body.startswith(b"PK"):
        return (file_name, len(body), "ERR not ZIP")

    raw_dir.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(body)
    return (file_name, len(body), "ok")


def extract_zip(archive: Path, out_dir: Path) -> list[str]:
    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()
        zf.extractall(out_dir)
    return names


def extract_lhc(archive: Path, out_dir: Path, sevenzip: str) -> list[str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    res = subprocess.run(
        [sevenzip, "x", f"-o{out_dir}", "-y", str(archive)],
        check=True,
        capture_output=True,
        text=True,
    )
    extracted: list[str] = []
    for line in res.stdout.splitlines():
        # 7z prints "- filename" for each extracted entry
        s = line.strip()
        if s.startswith("- "):
            extracted.append(s[2:])
    return extracted


def fetch_songs(
    db_path: Path,
    include_internal: bool,
    filter_like: str | None,
) -> list[tuple[str, str, str, str]]:
    conn = sqlite3.connect(str(db_path))
    sql = "SELECT file_name, title, compress_type, iap_contents_id FROM songs"
    where: list[str] = []
    params: list[str] = []
    if not include_internal:
        where.append("iap_contents_id != '-'")
    if filter_like:
        where.append("file_name LIKE ?")
        params.append(filter_like)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY file_name"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--db", default="SongDB.sqlite3", help="MobileSongBank SongDB.sqlite3 path")
    ap.add_argument("--out", default="msb_downloads", help="output directory")
    ap.add_argument("--filter", default=None, help="SQL LIKE pattern on file_name, e.g. 001AC%%")
    ap.add_argument("--workers", type=int, default=4, help="parallel downloads")
    ap.add_argument(
        "--include-internal",
        action="store_true",
        help="also fetch the 165 bundled songs (iap_contents_id='-')",
    )
    ap.add_argument("--no-extract", action="store_true", help="keep archives only, do not extract")
    ap.add_argument("--skip-existing", action="store_true", help="skip raw download if file exists")
    args = ap.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"db not found: {db_path}", file=sys.stderr)
        return 2

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    songs = fetch_songs(db_path, args.include_internal, args.filter)
    if not songs:
        print("no matching songs in DB")
        return 0

    sevenzip = shutil.which("7z") or shutil.which("7zz")
    has_lhc = any(s[2] == "lhc" for s in songs)
    if has_lhc and not args.no_extract and sevenzip is None:
        print(
            "warning: 7z not found in PATH; .lhc archives will be downloaded but not extracted.\n"
            "         install with: brew install p7zip   (or pass --no-extract to silence)",
            file=sys.stderr,
        )

    print(f"target: {len(songs)} songs")
    print(f"output: {out_dir.resolve()}")

    ok = cached = empty = err = extracted_count = 0
    started = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {
            pool.submit(
                download_one,
                file_name,
                compress_type,
                out_dir,
                skip_existing=args.skip_existing,
            ): (file_name, compress_type)
            for file_name, _title, compress_type, _iap in songs
        }
        for i, fut in enumerate(concurrent.futures.as_completed(futs), 1):
            file_name, compress_type = futs[fut]
            _fn, size, status = fut.result()
            if status == "ok":
                ok += 1
                tag = "OK "
            elif status == "cached":
                cached += 1
                tag = "HIT"
            elif status == "empty":
                empty += 1
                tag = "EMP"
            else:
                err += 1
                tag = "ERR"

            ext_msg = ""
            if (
                status in ("ok", "cached")
                and not args.no_extract
                and compress_type in ("lhc", "zip")
            ):
                archive = out_dir / "raw" / f"{file_name}.{compress_type}"
                extract_dir = out_dir / "extracted"
                try:
                    if compress_type == "zip":
                        extract_zip(archive, extract_dir)
                        extracted_count += 1
                    elif compress_type == "lhc" and sevenzip:
                        extract_lhc(archive, extract_dir, sevenzip)
                        extracted_count += 1
                except (zipfile.BadZipFile, subprocess.CalledProcessError, OSError) as e:
                    ext_msg = f"  EXTRACT-FAIL {e.__class__.__name__}"

            print(
                f"[{i:4d}/{len(songs)}] {tag} {size:>9d}  "
                f"{file_name}.{compress_type}  "
                f"{'' if status in ('ok', 'cached') else status}{ext_msg}"
            )

    elapsed = time.monotonic() - started
    print(
        f"\ndone in {elapsed:.1f}s: ok={ok} cached={cached} empty={empty} err={err} "
        f"extracted={extracted_count}"
    )
    return 0 if err == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
