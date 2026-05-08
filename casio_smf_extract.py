#!/usr/bin/env python3
"""
casio_smf_extract.py
────────────────────
Casio アプリ内蔵曲データ (.bin) から標準MIDIファイル (SMF Format 1) を抽出するツール。
MobileSongBank / ChordanaPlay どちらの .bin にも対応。

使い方:
  python3 casio_smf_extract.py <file.bin> [file2.bin ...] [options]

オプション:
  --db <SongDB.sqlite3>   曲名DBを指定 (省略可)
  --out <dir>             出力先ディレクトリ (デフォルト: ./casio_midi_output)

例:
  # 単一ファイル
  python3 casio_smf_extract.py InternalSongsData.bin

  # 複数ファイル + DB指定
  python3 casio_smf_extract.py InternalSongsData.bin InternalSongsData540.bin --db SongDB.sqlite3

  # 出力先を指定
  python3 casio_smf_extract.py ChordanaPlay/InternalSongsData.bin --out chordana_midi
"""

import sys
import os
import re
import struct
import sqlite3
import zipfile
import argparse

# ─── ビット置換テーブル ───────────────────────────
# libsssg.so の read_InternalSongData (ARM64, VA: 0x94fd8) から解析
TABLE = [5, 2, 3, 7, 1, 0, 6, 4]

_DECODE_TABLE = bytes(
    sum(((b >> i) & 1) << TABLE[i] for i in range(8))
    for b in range(256)
)

def decode_raw(raw: bytes) -> bytes:
    return bytes(_DECODE_TABLE[b] for b in raw)

# ─── インデックス自動検出 ──────────────────────────
MIDI_MAGIC = b'MThd'
ENTRY_SIZE = 8  # offset(4) + size(4)

def detect_song_count(data: bytes) -> int:
    """
    インデックスの有効エントリ数を自動検出する。
    オフセットが単調増加かつサイズがファイル範囲内である
    最大のエントリ数を返す。
    """
    fsize = len(data)
    count = 0
    for i in range(256):  # 上限256曲
        base = i * ENTRY_SIZE
        if base + ENTRY_SIZE > fsize:
            break
        off, sz = struct.unpack_from('<II', data, base)
        if sz == 0 or sz > fsize or off > fsize or off + sz > fsize * 2:
            break
        count += 1
    return count

# ─── MIDI トラック名の取得 ────────────────────────
def get_midi_track_name(midi_data: bytes) -> str:
    """SMF の最初の FF 03 (Track Name) メタイベントを取得する"""
    p = midi_data.find(b'\xff\x03')
    if p < 0:
        return ''
    name_len = midi_data[p + 2]
    try:
        return midi_data[p + 3 : p + 3 + name_len].decode('utf-8', errors='replace').strip()
    except Exception:
        return ''

def safe_filename(name: str) -> str:
    """ファイル名として使える文字列に変換する"""
    name = re.sub(r'[\\/:*?"<>|]', '_', name)
    name = name.strip('. ')
    return name[:80] if name else ''

# ─── SongDB の読み込み ────────────────────────────
def load_song_db(db_path: str) -> dict:
    """
    SongDB.sqlite3 を読み込んで {(ds_id, 0-based_index): file_name} を返す。
    db_index 列の値はスペース区切りで各データセットのインデックス番号を示す。
    'n' は未収録を意味する。
    """
    song_map = {}
    if not db_path or not os.path.exists(db_path):
        return song_map
    try:
        conn = sqlite3.connect(db_path)
        for file_name, db_index in conn.execute("SELECT file_name, db_index FROM songs"):
            for ds_id, part in enumerate(db_index.split()):
                if part != 'n' and part != '-':
                    try:
                        song_map[(ds_id, int(part) - 1)] = file_name
                    except ValueError:
                        pass
        conn.close()
    except Exception as e:
        print(f"  [警告] SongDB 読み込み失敗: {e}", file=sys.stderr)
    return song_map

def guess_ds_id(bin_path: str) -> int | None:
    """
    ファイル名のパターンから SongDB の ds_id を推測する。
    InternalSongsData.bin      → 0
    InternalSongsData512.bin   → 1
    InternalSongsData515.bin   → 2
    InternalSongsData520.bin   → 3
    InternalSongsData530.bin   → 4
    InternalSongsData540.bin   → 5
    それ以外                    → None
    """
    stem = os.path.splitext(os.path.basename(bin_path))[0]  # e.g. "InternalSongsData540"
    suffix = stem.replace('InternalSongsData', '')           # e.g. "540" or ""
    mapping = {'': 0, '512': 1, '515': 2, '520': 3, '530': 4, '540': 5}
    return mapping.get(suffix, None)

# ─── 単一 .bin ファイルの変換 ─────────────────────
def extract_bin(bin_path: str, song_map: dict, out_dir: str) -> int:
    """
    bin_path のデータを全曲変換して out_dir に書き出す。
    変換に成功した曲数を返す。
    """
    data = open(bin_path, 'rb').read()

    n_songs = detect_song_count(data)
    if n_songs == 0:
        print(f"  [エラー] 有効なインデックスが見つかりません: {bin_path}", file=sys.stderr)
        return 0

    index_size = n_songs * ENTRY_SIZE
    ds_id = guess_ds_id(bin_path)

    os.makedirs(out_dir, exist_ok=True)

    written = 0
    used_names: set[str] = set()

    for idx in range(n_songs):
        off, sz = struct.unpack_from('<II', data, idx * ENTRY_SIZE)
        data_start = index_size + off
        if sz == 0 or data_start + sz > len(data):
            continue

        decoded = decode_raw(data[data_start : data_start + sz])
        if decoded[:4] != MIDI_MAGIC:
            continue

        # ファイル名の決定: SongDB > MIDI内部名 > song_NNN
        base_name = ''
        if ds_id is not None and song_map:
            base_name = song_map.get((ds_id, idx), '')
        if not base_name:
            base_name = safe_filename(get_midi_track_name(decoded))
        if not base_name:
            base_name = f'song_{idx:03d}'

        # 重複回避
        candidate = base_name
        suffix = 1
        while candidate in used_names:
            candidate = f'{base_name}_{suffix}'
            suffix += 1
        used_names.add(candidate)

        out_path = os.path.join(out_dir, candidate + '.mid')
        open(out_path, 'wb').write(decoded)
        written += 1

    return written

# ─── メイン ──────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description='Casio .bin から標準MIDIを抽出するツール',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('bins', nargs='+', metavar='file.bin',
                        help='変換する .bin ファイル（複数指定可）')
    parser.add_argument('--db', metavar='SongDB.sqlite3',
                        help='曲名データベース (省略可)')
    parser.add_argument('--out', metavar='DIR', default='casio_midi_output',
                        help='出力先ディレクトリ (デフォルト: casio_midi_output)')
    args = parser.parse_args()

    song_map = load_song_db(args.db)
    if song_map:
        print(f"SongDB: {len(song_map)} エントリ読み込み完了")
    elif args.db:
        print("SongDB: 読み込み失敗 → MIDI内部名で出力")
    else:
        print("SongDB なし → MIDI内部名で出力")

    total = 0
    used_dirs: list[str] = []
    multi = len(args.bins) > 1

    for bin_path in args.bins:
        if not os.path.exists(bin_path):
            print(f"  [スキップ] ファイルが見つかりません: {bin_path}")
            continue

        # 複数ファイルの場合はサブフォルダに分ける
        stem = os.path.splitext(os.path.basename(bin_path))[0]
        out_dir = os.path.join(args.out, stem) if multi else args.out

        n = extract_bin(bin_path, song_map, out_dir)
        label = stem if multi else os.path.basename(bin_path)
        print(f"  {label}: {n} 曲")
        total += n
        if n > 0:
            used_dirs.append(out_dir)

    if total == 0:
        print("変換できる曲が見つかりませんでした。")
        sys.exit(1)

    print(f"\n合計: {total} 曲を {args.out}/ に出力")

    # ZIP 作成
    zip_path = args.out.rstrip('/\\') + '.zip'
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for d in used_dirs:
            rel_base = os.path.relpath(d, os.path.dirname(args.out))
            for fname in sorted(os.listdir(d)):
                if fname.endswith('.mid'):
                    arc_name = (os.path.join(rel_base, fname)
                                if multi else fname)
                    zf.write(os.path.join(d, fname), arc_name)
    print(f"ZIP: {zip_path} ({os.path.getsize(zip_path) // 1024} KB)")


if __name__ == '__main__':
    main()
