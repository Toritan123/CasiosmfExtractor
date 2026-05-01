#!/usr/bin/env python3
"""
casio_smf_extract.py
────────────────────
Casio MobileSongBank APK の InternalSongsData*.bin から
標準MIDIファイル (SMF Format 1) を一括抽出するツール。

【動作原理】
  各 .bin ファイルは 200 曲分のインデックス(200×8 バイト = 0x640 バイト)
  に続いてビット置換スクランブルされたデータが格納されている。
  各バイトに TABLE=[5,2,3,7,1,0,6,4] のビット置換を適用してデコードすると
  標準MIDIファイル(MThd マジック)が現れる。

【必要なファイル】
  InternalSongsData.bin       ← デフォルトセット
  InternalSongsData512.bin    ← LK-512 用
  InternalSongsData515.bin    ← LK-515 用
  InternalSongsData520.bin    ← LK-520 用
  InternalSongsData530.bin    ← LK-530 用
  InternalSongsData540.bin    ← LK-540 用 (新バージョン)
  sql/SongDB.sqlite3 または SongDB.sqlite3  ← 曲名データベース (省略可)

【使い方】
  python3 casio_smf_extract.py <assets_dir> [output_dir]

  assets_dir : APK を解凍した assets/ フォルダへのパス
               または InternalSongsData*.bin と SongDB.sqlite3 を
               置いたフォルダへのパス
  output_dir : 出力先 (省略時: ./casio_midi_output)

【出力】
  output_dir/
    default/  001AC_Doraemon.mid  ...
    LK512/    ...
    LK515/    ...
    LK520/    ...
    LK530/    ...
    LK540/    001AC_LilacMrs.mid  ...  (新バージョンのみ)
  casio_midi_output.zip  (同梱)
"""

import sys
import os
import struct
import sqlite3
import zipfile

# ─── ビット置換テーブル ─────────────────────────────
# libsssg.so の read_InternalSongData (VA: 0x94fd8) から解析
TABLE = [5, 2, 3, 7, 1, 0, 6, 4]

# テーブルを先に全バイト展開しておく (高速化)
_DECODE_TABLE = bytes(
    sum(((b >> i) & 1) << TABLE[i] for i in range(8))
    for b in range(256)
)

def decode_raw(raw: bytes) -> bytes:
    """ビット置換でデコードする"""
    return bytes(_DECODE_TABLE[b] for b in raw)

# ─── ファイル構造定数 ─────────────────────────────
INDEX_ENTRY_SIZE = 8      # offset(4) + size(4)
MAX_SONGS        = 200
INDEX_SIZE       = MAX_SONGS * INDEX_ENTRY_SIZE   # = 0x640
MIDI_MAGIC       = b'MThd'

# ─── データセット定義 ─────────────────────────────
# (ファイル名, SongDB の db_index 内での位置(0始まり), 出力フォルダ名)
DATASETS = [
    ('InternalSongsData.bin',     0, 'default'),
    ('InternalSongsData512.bin',  1, 'LK512'),
    ('InternalSongsData515.bin',  2, 'LK515'),
    ('InternalSongsData520.bin',  3, 'LK520'),
    ('InternalSongsData530.bin',  4, 'LK530'),
    ('InternalSongsData540.bin',  5, 'LK540'),  # 新バージョン追加
]

# ─── メイン変換 ───────────────────────────────────
def extract_songs(bin_path: str, db_song_map: dict, ds_id: int, out_dir: str):
    data = open(bin_path, 'rb').read()
    os.makedirs(out_dir, exist_ok=True)

    written = 0
    for idx in range(MAX_SONGS):
        offset, size = struct.unpack_from('<II', data, idx * INDEX_ENTRY_SIZE)
        if size == 0:
            continue
        data_start = INDEX_SIZE + offset
        if data_start + size > len(data):
            continue

        raw     = data[data_start : data_start + size]
        decoded = decode_raw(raw)

        if decoded[:4] != MIDI_MAGIC:
            continue

        key       = (ds_id, idx)
        base_name = db_song_map.get(key, f'song_{idx:03d}')
        safe_name = base_name.replace('/', '_').replace('\\', '_').replace(':', '_')
        out_path  = os.path.join(out_dir, safe_name + '.mid')

        with open(out_path, 'wb') as f:
            f.write(decoded)
        written += 1

    return written


def load_song_db(db_path: str) -> dict:
    """
    SongDB.sqlite3 を読み込んで {(ds_id, 0-based_index): file_name} を返す。
    db_index の値は旧バージョンで5値、新バージョン(LK-540対応)で6値。
    """
    song_map = {}
    if not os.path.exists(db_path):
        return song_map
    try:
        conn   = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT file_name, db_index FROM songs")
        for file_name, db_index in cursor.fetchall():
            for ds_id, part in enumerate(db_index.split()):
                if part != 'n':
                    try:
                        idx = int(part) - 1   # 1-indexed → 0-indexed
                        song_map[(ds_id, idx)] = file_name
                    except ValueError:
                        pass
        conn.close()
    except Exception as e:
        print(f"  [警告] SongDB 読み込み失敗: {e}", file=sys.stderr)
    return song_map


def find_db(assets_dir: str) -> str:
    """SongDB.sqlite3 を assets_dir 直下または sql/ サブフォルダから探す"""
    for candidate in [
        os.path.join(assets_dir, 'SongDB.sqlite3'),
        os.path.join(assets_dir, 'sql', 'SongDB.sqlite3'),
    ]:
        if os.path.exists(candidate):
            return candidate
    return ''


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    assets_dir = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) >= 3 else 'casio_midi_output'

    db_path  = find_db(assets_dir)
    song_map = load_song_db(db_path)
    if song_map:
        print(f"SongDB: {len(song_map)} エントリ読み込み完了")
    else:
        print("SongDB なし → song_000.mid 形式で出力")

    total = 0
    processed_ds = []
    for bin_name, ds_id, ds_name in DATASETS:
        bin_path = os.path.join(assets_dir, bin_name)
        if not os.path.exists(bin_path):
            continue
        ds_out = os.path.join(output_dir, ds_name)
        n = extract_songs(bin_path, song_map, ds_id, ds_out)
        print(f"  {ds_name:8s}: {n:3d} 曲")
        total += n
        processed_ds.append(ds_name)

    if total == 0:
        print("変換できる曲が見つかりませんでした。")
        print(f"'{assets_dir}' に InternalSongsData*.bin が存在するか確認してください。")
        sys.exit(1)

    print(f"\n合計: {total} 曲を {output_dir}/ に出力")

    zip_path = output_dir.rstrip('/\\') + '.zip'
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for ds_name in processed_ds:
            ds_dir = os.path.join(output_dir, ds_name)
            if not os.path.isdir(ds_dir): continue
            for fname in sorted(os.listdir(ds_dir)):
                if fname.endswith('.mid'):
                    zf.write(os.path.join(ds_dir, fname), f'{ds_name}/{fname}')
    print(f"ZIP: {zip_path} ({os.path.getsize(zip_path) // 1024} KB)")


if __name__ == '__main__':
    main()
