# casio-smf-extractor

Casio アプリの内蔵曲データ (`.bin`) から標準MIDIファイル (SMF Format 1) を抽出するツール。
**CASIO MUSIC SPACE** のフル曲 MIDI/MP3/PDF を公開エンドポイントから一括ダウンロードする補助スクリプトも同梱。

対応アプリ:
- **MobileSongBank** (`jp.co.casio.MobileSongBank`) — bin 抽出
- **ChordanaPlay** (`jp.co.casio.chordanaplay`) — bin 抽出
- **CASIO MUSIC SPACE** (`jp.co.casio.CasioMusicCity`) — bin 抽出 + Web API ダウンロード

[English below](#english)

---

## 使い方

### 1. .bin ファイルを用意する

APK を ZIP として展開すると `assets/` 内に `InternalSongsData*.bin` が見つかります。

```bash
cp jp.co.casio.MobileSongBank.apk msb.zip
unzip msb.zip -d msb/
ls msb/assets/InternalSongsData*.bin
```

### 2. 変換する

```bash
python3 casio_smf_extract.py <file.bin> [file2.bin ...] [--db SongDB.sqlite3] [--out 出力先]
```

**例:**

```bash
# 単一ファイル（曲名はMIDI内部名を使用）
python3 casio_smf_extract.py InternalSongsData.bin

# 複数ファイル＋曲名DBを指定
python3 casio_smf_extract.py InternalSongsData.bin InternalSongsData540.bin \
    --db SongDB.sqlite3 --out casio_midi
```

**出力例（複数ファイル指定時）:**
```
SongDB: 1200 エントリ読み込み完了
  InternalSongsData  : 200 曲
  InternalSongsData540: 200 曲

合計: 400 曲を casio_midi/ に出力
ZIP: casio_midi.zip (XXXX KB)
```

### オプション

| オプション | 内容 |
|-----------|------|
| `--db SongDB.sqlite3` | 曲名データベース（assets/sql/ 内または直置き、省略可） |
| `--out DIR` | 出力先ディレクトリ（デフォルト: `casio_midi_output`） |

SongDB を指定しない場合はMIDIファイル内部のトラック名を曲名として使用します。

CASIO MUSIC SPACE の `cms_songs.db` も `--db` に指定可能（自動判別）。
`InternalSongsData.bin` の SP 50曲が rowid 順で `ML001_Nocturne` 等の file_id に紐付きます。

```bash
python3 casio_smf_extract.py \
    /path/to/jp.co.casio.CasioMusicCity/assets/InternalSongsData.bin \
    --db /path/to/assets/DB/cms_songs.db \
    --out cms_bin_midi
```

---

## CASIO MUSIC SPACE フル曲のダウンロード

`casio_cms_download.py` は CASIO MUSIC SPACE の公開エンドポイント
`https://musicapp.casio.jp/dlmusicdata/dlmusicdata_android.php` に
POST して MIDI / MP3 / PDF / TXT を一括取得するスクリプトです。
**認証は不要** ですが、`cms_songs.db`（APK 内 `assets/DB/`）が必要です。

```bash
# DP曲のMIDIのみ取得
python3 casio_cms_download.py \
    --db /path/to/assets/DB/cms_songs.db \
    --types DP --ext mid --workers 10

# SP+DP 全506曲のMIDI+PDF+MP3+TXT を取得
python3 casio_cms_download.py \
    --db /path/to/assets/DB/cms_songs.db \
    --ext mid,mp3,pdf,txt --workers 10 --skip-existing
```

| オプション | デフォルト | 内容 |
|-----------|-----------|------|
| `--db` | `assets/DB/cms_songs.db` | `cms_songs.db` のパス |
| `--out` | `cms_downloads` | 出力先（拡張子別サブフォルダに保存） |
| `--ext` | `mid` | カンマ区切り: `mid,mp3,pdf,txt` |
| `--types` | `SP,DP` | カンマ区切り: `SP`=内蔵, `DP`=ダウンロード |
| `--filter` | `(なし)` | SQL LIKE で file_id を絞り込み（例: `BY%%`） |
| `--workers` | `4` | 並列数 |
| `--skip-existing` | off | 既存ファイルをスキップ |

bin から抽出した SP 50曲（簡易MIDI）と API で取得したフル版MIDIは別データです
（API版は2〜10倍長く、伴奏トラック付き）。両方保存する価値があります。

### 動作環境

- Python 3.6 以上
- 外部ライブラリ不要（標準ライブラリのみ）

---

## 動作原理

各 `.bin` ファイルは以下の構造を持ちます：

```
[インデックス領域]  N × 8 バイト
  各エントリ: [データ領域内オフセット: uint32 LE][データサイズ: uint32 LE]

[データ領域]
  各曲データ: ビット置換でスクランブルされた SMF
```

曲数 N はファイルによって異なります（本ツールは自動検出します）。

### ビット置換テーブル

ネイティブライブラリ `libsssg.so` の `read_InternalSongData` 関数（ARM64, VA: `0x94fd8`）を逆アセンブルして解析した結果、各バイトに以下のビット置換が適用されています：

```
TABLE = [5, 2, 3, 7, 1, 0, 6, 4]
# 入力バイトのビット i → 出力バイトのビット TABLE[i]
```

```python
_DECODE_TABLE = bytes(
    sum(((b >> i) & 1) << TABLE[i] for i in range(8))
    for b in range(256)
)
decoded = bytes(_DECODE_TABLE[b] for b in raw)
```

デコード後は標準MIDIファイル（`MThd` マジック）として再生できます。

---

## 注意事項

- 抽出した MIDI に含まれる楽曲の著作権は各権利者に帰属します。個人的な研究・学習目的以外での使用には注意してください。
- APK の入手・使用は適法に行ってください。
- 本ツールは Casio の公式サービスとは無関係のリバースエンジニアリング研究の成果です。

---

<a name="english"></a>

## English

A tool to extract standard MIDI files (SMF Format 1) from Casio app built-in song data (`.bin` files),
plus a companion downloader for the full MIDI/MP3/PDF assets of **CASIO MUSIC SPACE**.

Supports:
- **MobileSongBank** (`jp.co.casio.MobileSongBank`) — bin extraction
- **ChordanaPlay** (`jp.co.casio.chordanaplay`) — bin extraction
- **CASIO MUSIC SPACE** (`jp.co.casio.CasioMusicCity`) — bin extraction + Web API download

### Usage

```bash
python3 casio_smf_extract.py <file.bin> [file2.bin ...] [--db SongDB.sqlite3] [--out DIR]
```

**Examples:**

```bash
# Single file
python3 casio_smf_extract.py InternalSongsData.bin

# Multiple files with song name DB
python3 casio_smf_extract.py InternalSongsData.bin InternalSongsData540.bin \
    --db SongDB.sqlite3 --out casio_midi

# CASIO MUSIC SPACE (cms_songs.db is auto-detected)
python3 casio_smf_extract.py InternalSongsData.bin --db cms_songs.db
```

### Downloading the full CASIO MUSIC SPACE catalog (506 songs)

`casio_cms_download.py` POSTs to Casio's public endpoint
`https://musicapp.casio.jp/dlmusicdata/dlmusicdata_android.php` — **no auth required**.
You need `cms_songs.db` (from the CASIO MUSIC SPACE APK `assets/DB/`).

```bash
# All MIDI files (SP + DP, 506 songs)
python3 casio_cms_download.py --db cms_songs.db --ext mid --workers 10

# MIDI + score PDF + accompaniment MP3 + sync TXT
python3 casio_cms_download.py --db cms_songs.db \
    --ext mid,mp3,pdf,txt --workers 10 --skip-existing
```

The 50 SP songs that ship inside `InternalSongsData.bin` are simplified
versions for on-keyboard playback. The API serves richer full versions
(2–10× longer, with accompaniment tracks) — both are worth keeping.

### Requirements

- Python 3.6+
- No external dependencies

### How it works

Each `.bin` file contains an index region followed by scrambled MIDI data. By reverse-engineering `libsssg.so` (ARM64), the bit-permutation table was recovered:

```
TABLE = [5, 2, 3, 7, 1, 0, 6, 4]
```

After decoding, each entry is a valid SMF Format 1 MIDI file. The number of songs per file is auto-detected.

### Disclaimer

Extracted MIDI files are copyrighted by their respective owners. This tool is for **personal research purposes only**. Obtain APKs only through legitimate means.

---

## License

MIT — see [LICENSE](LICENSE)
