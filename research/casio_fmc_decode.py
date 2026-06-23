#!/usr/bin/env python3
"""
Casio .fmc (fingering guide) decoder — WORK IN PROGRESS scaffold.

The .fmc body is compressed with M.Hiroi's "BlockSorting + MTF + ZLE +
RangeCoder" pipeline (libsssg.so decode() @0x73220; binary string
"BlockSroting and RangeCoder Compressor Sample Program ver 2.0").

Decompression pipeline (per block):
    RangeCoder(Freq012 adaptive model) -> MTF decode -> RLE2/ZLE decode
    -> inverse BWT (block sort) -> plaintext

Container (big-endian u32 fields, from the reference bsrc1.py):
    per block:  size, top(BWT primary index), r_size  then range-coded stream

Plaintext = 10-byte records, left-hand channel then right-hand channel:
    timestamp u64 LE | note u8 | finger u8 (1..5)
(confirmed from libsssg.so read_Fingering/write_Fingering fwrite layout)

STATUS:
  [done] RangeCoder core (Schindler/Subbotin, exact constants below)
  [done] static Freq, inverse BWT, container framing, record format
  [TODO] Freq012 adaptive model (freq.py)  <-- bit-exact, REQUIRED
  [TODO] mtf2_decode, rle_decode2 (ZLE)     <-- bit-exact, REQUIRED
  [TODO] confirm casi header skip + per-block loop against real files
  [TODO] validate decoded notes/times against the bundled .mid / .cmf

Reference: https://www.nct9.ne.jp/m_hiroi/light/pyalgo36.html .. pyalgo49.html
"""
from __future__ import annotations

import struct
import sys
from array import array
from pathlib import Path

# --- RangeCoder (verbatim constants from M.Hiroi pyalgo37, Schindler-style) ---
MAX_RANGE = 0xffffffff
MIN_RANGE = 0x10000
MASK = 0xffffffff
MASK1 = 0xff000000
SHIFT = 24


class ByteReader:
    def __init__(self, data: bytes, pos: int = 0):
        self.data = data
        self.pos = pos

    def getc(self) -> int:
        if self.pos >= len(self.data):
            return 0  # range coder reads a few trailing bytes past end
        b = self.data[self.pos]
        self.pos += 1
        return b


class RangeCoder:
    def __init__(self, stream: ByteReader):
        self.s = stream
        self.range_ = MAX_RANGE
        self.low = 0
        self.code = 0
        for _ in range(4):
            self.code = ((self.code << 8) + self.s.getc()) & MASK

    def decode_normalize(self):
        while (self.low & MASK1) == ((self.low + self.range_) & MASK1):
            self.code = ((self.code << 8) & MASK) + self.s.getc()
            self.low = (self.low << 8) & MASK
            self.range_ = (self.range_ << 8) & MASK
        while self.range_ < MIN_RANGE:
            self.range_ = (MIN_RANGE - (self.low & (MIN_RANGE - 1))) << 8
            self.code = ((self.code << 8) & MASK) + self.s.getc()
            self.low = (self.low << 8) & MASK


class FreqStatic:
    """Static cumulative-frequency model (M.Hiroi pyalgo37). Kept as reference;
    the real .fmc uses the ADAPTIVE Freq012 model (see TODO)."""

    def __init__(self, count):
        self.size = len(count)
        self.count = list(count)
        self.count_sum = [0] * (self.size + 1)
        for x in range(self.size):
            self.count_sum[x + 1] = self.count_sum[x] + self.count[x]

    def decode(self, rc: RangeCoder) -> int:
        total = self.count_sum[self.size]
        temp = rc.range_ // total
        value = (rc.code - rc.low) // temp
        # binary search for symbol
        i, j = 0, self.size - 1
        while i < j:
            k = (i + j) // 2
            if self.count_sum[k + 1] <= value:
                i = k + 1
            else:
                j = k
        c = i
        rc.low = (rc.low + temp * self.count_sum[c]) & MASK
        rc.range_ = temp * self.count[c]
        rc.decode_normalize()
        return c


# --- inverse BWT (block sort decode), M.Hiroi pyalgo49 ------------------------
def inverse_bwt(buff: bytes, top: int) -> bytes:
    # Exact transcription of M.Hiroi pyalgo49 inverse block sort.
    size = len(buff)
    count = [0] * 256
    for x in range(size):
        count[buff[x]] += 1
    for x in range(1, 256):
        count[x] += count[x - 1]          # inclusive cumulative
    idx = [0] * size
    for x in range(size - 1, -1, -1):
        c = buff[x]
        count[c] -= 1
        idx[count[c]] = x
    out = bytearray(size)
    x = idx[top]
    for i in range(size):
        out[i] = buff[x]
        x = idx[x]
    return bytes(out)


def read_u32_be(r: ByteReader) -> int:
    n = 0
    for _ in range(4):
        n = (n << 8) + r.getc()
    return n


# --- records ------------------------------------------------------------------
def parse_records(plain: bytes):
    """10-byte records: u64 LE time, u8 note, u8 finger."""
    recs = []
    for i in range(0, len(plain) - 9, 10):
        t = struct.unpack_from("<Q", plain, i)[0]
        note = plain[i + 8]
        finger = plain[i + 9]
        recs.append((t, note, finger))
    return recs


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    data = Path(sys.argv[1]).read_bytes()
    if data[:4] != b"casi":
        print(f"not a .fmc (magic {data[:4]!r})", file=sys.stderr)
        return 2
    print("header:", data[:12].hex(" "))
    print("NOTE: decoder incomplete — Freq012 / mtf2 / rle2 still TODO.")
    print("      This scaffold has the RangeCoder, inverse BWT, container")
    print("      framing and record parser ready; the adaptive model and")
    print("      MTF/ZLE stages must be filled in (see module docstring).")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
