#!/usr/bin/env python3
"""
CMFF (Casio Music File Format) container parser / analyzer.

Reverse-engineered from libsssg.so (ARM64) exported symbols:
  get_CmfHeader, get_CmfDeltaTime, get_CmfTrackCommand, get_CmfNoteOn,
  get_CmfControlChange, get_CmfProgramChange, get_CmfPitchBend,
  get_CmfChannelPressure, get_CmfDrumPartBankSelect, get_CmfMidiTrack,
  get_CmfSystemTrack, get_CmfStepLessonAccompOffTrackMute.

Container layout:
    offset 0   : "CMFF"            magic (4 bytes)
    offset 4   : header_len        uint32 LE  (bytes from offset 8 to first TRAK)
    offset 8   : header body       version/format tag bytes + fixed title field
    ...        : 17 "TRAK" chunks   (16 MIDI channels + 1 system track)

TRAK chunk header (12 bytes), then payload[length]:
    "TRAK"            4 bytes  marker
    00 ab 00 00       4 bytes  constant (0x0000ab00 — track type/flags)
    length            uint32 LE  payload byte count
    payload[length]   event stream (next chunk follows immediately)

Encoding primitives (from disassembly):
    track command : 2 bytes  [(cmd & 0x7f) | 0x80, cmd >> 7]   (status bytes set bit7)
    delta time    : little-endian 7-bit VLQ; bit7 = "more bytes follow", LSB first

This tool validates the container across files and dumps the structure.
Full event-stream → MIDI reconstruction is intentionally out of scope: the
matching .mid already ships in the same .zip; the CMF's unique payload is the
lesson metadata (fingering / chord / LCD / accompaniment-mute), flagged below.

Usage:
    python3 casio_cmf_parse.py <file.cmf> [...]        # dump structure
    python3 casio_cmf_parse.py --scan DIR              # validate all *.cmf
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

MAGIC = b"CMFF"


def find_chunks(data: bytes, start: int) -> list[tuple[str, int, int]]:
    """Return [(tag, payload_offset, payload_len)] for TRAK chunks.

    Chunk header is 12 bytes: "TRAK" + 4-byte constant (00 ab 00 00) +
    uint32 LE payload length. Payload follows; next chunk is contiguous.
    """
    chunks: list[tuple[str, int, int]] = []
    pos = start
    n = len(data)
    while pos + 12 <= n:
        tag = data[pos : pos + 4]
        if tag != b"TRAK":
            break
        marker = struct.unpack_from("<I", data, pos + 4)[0]  # noqa: F841 (0xab00)
        length = struct.unpack_from("<I", data, pos + 8)[0]
        payload = pos + 12
        chunks.append((tag.decode("ascii", "replace"), payload, length))
        pos = payload + length
    return chunks


def parse(path: Path) -> dict:
    data = path.read_bytes()
    info: dict = {"path": str(path), "size": len(data), "ok": False}
    if data[:4] != MAGIC:
        info["error"] = f"bad magic {data[:4]!r}"
        return info

    header_len = struct.unpack_from("<I", data, 4)[0]
    first_trak = 8 + header_len
    info["header_len"] = header_len
    info["first_trak"] = first_trak

    # Title: ASCII run inside the header body (after the leading tag bytes).
    body = data[8:first_trak]
    title = ""
    # The title is the longest printable ASCII run in the header body.
    cur = []
    runs = []
    for b in body:
        if 0x20 <= b < 0x7F:
            cur.append(b)
        else:
            if len(cur) >= 2:
                runs.append(bytes(cur))
            cur = []
    if len(cur) >= 2:
        runs.append(bytes(cur))
    if runs:
        title = max(runs, key=len).decode("ascii").rstrip()
    info["title"] = title

    # Locate first TRAK; if header_len is off, scan for it.
    if data[first_trak : first_trak + 4] != b"TRAK":
        idx = data.find(b"TRAK", 8)
        info["trak_scan_fallback"] = idx
        first_trak = idx if idx != -1 else first_trak

    chunks = find_chunks(data, first_trak)
    info["chunks"] = chunks
    info["n_chunks"] = len(chunks)
    # Consistency: does the last chunk reach (approximately) EOF?
    if chunks:
        tag, payoff, paylen = chunks[-1]
        info["bytes_after_last_chunk"] = len(data) - (payoff + paylen)
    info["ok"] = bool(chunks) and data[:4] == MAGIC
    return info


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("files", nargs="*", help=".cmf files to dump")
    ap.add_argument("--scan", metavar="DIR", help="validate every *.cmf under DIR")
    args = ap.parse_args()

    if args.scan:
        files = sorted(Path(args.scan).glob("*.cmf"))
        if not files:
            print(f"no .cmf under {args.scan}", file=sys.stderr)
            return 2
        ok = bad = 0
        chunk_hist: dict[int, int] = {}
        tail_off: dict[int, int] = {}
        for f in files:
            info = parse(f)
            if info["ok"]:
                ok += 1
                chunk_hist[info["n_chunks"]] = chunk_hist.get(info["n_chunks"], 0) + 1
                t = info.get("bytes_after_last_chunk", None)
                if t is not None:
                    tail_off[t] = tail_off.get(t, 0) + 1
            else:
                bad += 1
                print(f"  BAD  {f.name}: {info.get('error', 'no chunks')}")
        print(f"\nscanned {len(files)}: ok={ok} bad={bad}")
        print(f"chunk-count histogram: {dict(sorted(chunk_hist.items()))}")
        print(f"bytes-after-last-chunk histogram: {dict(sorted(tail_off.items()))}")
        return 0 if bad == 0 else 1

    if not args.files:
        ap.print_help()
        return 2

    for fp in args.files:
        info = parse(Path(fp))
        print(f"\n=== {info['path']} ({info['size']} bytes) ===")
        if not info["ok"]:
            print(f"  ERROR: {info.get('error', 'no TRAK chunks found')}")
            continue
        print(f"  title       : {info['title']!r}")
        print(f"  header_len  : {info['header_len']} (first TRAK @ {info['first_trak']})")
        print(f"  chunks      : {info['n_chunks']}")
        for i, (tag, off, length) in enumerate(info["chunks"]):
            print(f"    [{i}] {tag} @ {off}  len={length}")
        print(f"  tail bytes  : {info.get('bytes_after_last_chunk')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
