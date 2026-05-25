# casio-smf-extractor

Casio アプリの内蔵曲データ (`.bin`) から標準MIDIファイル (SMF Format 1) を抽出するツール。
**MobileSongBank** および **CASIO MUSIC SPACE** のフル曲 MIDI を公開エンドポイントから一括ダウンロードする補助スクリプトも同梱。

対応アプリ:
- **MobileSongBank** (`jp.co.casio.MobileSongBank`) — bin 抽出 + Web API ダウンロード (709曲)
- **ChordanaPlay** (`jp.co.casio.chordanaplay`) — bin 抽出
- **CASIO MUSIC SPACE** (`jp.co.casio.CasioMusicCity`) — bin 抽出 + Web API ダウンロード (506曲)

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

## MobileSongBank 追加ダウンロード曲

`casio_msb_download.py` は MobileSongBank の公開エンドポイント
`https://mobilesongbank.com/dlfprcheck/dlfortrial.php` (`.lhc`) /
`dlfortrialzip.php` (`.zip`) に POST して、アプリ内課金の追加ダウンロード曲
709 曲を取得します。**認証不要**、`SongDB.sqlite3`（APK 内 `assets/sql/`）が必要です。

```bash
# 全 709 曲を 10 並列で取得＋自動解凍
python3 casio_msb_download.py \
    --db /path/to/assets/sql/SongDB.sqlite3 \
    --workers 10 --skip-existing

# 出力構成:
#   msb_downloads/raw/        <file_name>.lhc / .zip  (生アーカイブ)
#   msb_downloads/extracted/  <file_name>.mid (+ .cmf .fmc — zip 12曲のみ)
```

| オプション | デフォルト | 内容 |
|-----------|-----------|------|
| `--db` | `SongDB.sqlite3` | `SongDB.sqlite3` のパス |
| `--out` | `msb_downloads` | 出力先 |
| `--filter` | `(なし)` | SQL LIKE で file_name を絞り込み（例: `001AC%%`） |
| `--workers` | `4` | 並列数 |
| `--include-internal` | off | 内蔵曲 (`iap_contents_id='-'`) も対象に含める |
| `--no-extract` | off | アーカイブ展開を行わない |
| `--skip-existing` | off | 既存ファイルをスキップ |

`.lhc` は標準 LHA (lh5) 形式で、解凍に `7z` (`brew install p7zip`) が必要です。
`.zip` は Python 標準ライブラリで解凍します。レスポンスにはマジックバイト検査
(`-lh5` / `PK`) を行い、HTML エラーページの誤保存を防いでいます。

`LK*SB*` の 6 件は鍵盤機種別の「内蔵曲パック」で、中身は他の個別配信曲の束
（重複あり）。ユニーク MIDI は **703 曲** になります。

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
plus companion downloaders for the full MIDI catalogs of **MobileSongBank** and **CASIO MUSIC SPACE**.

Supports:
- **MobileSongBank** (`jp.co.casio.MobileSongBank`) — bin extraction + Web API download (709 songs)
- **ChordanaPlay** (`jp.co.casio.chordanaplay`) — bin extraction
- **CASIO MUSIC SPACE** (`jp.co.casio.CasioMusicCity`) — bin extraction + Web API download (506 songs)

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

### Downloading the full MobileSongBank catalog (709 songs)

`casio_msb_download.py` POSTs `filename=<file_name>.lhc` (or `.zip`) to
`https://mobilesongbank.com/dlfprcheck/dlfortrial.php` /
`dlfortrialzip.php` — **no auth required**.
You need `SongDB.sqlite3` (from the MobileSongBank APK `assets/sql/`).

```bash
# All 709 IAP songs, extracted into msb_downloads/extracted/*.mid
python3 casio_msb_download.py \
    --db /path/to/assets/sql/SongDB.sqlite3 \
    --workers 10 --skip-existing
```

`.lhc` archives are standard LHA (lh5) format and require `7z`
(`brew install p7zip`) to extract; `.zip` archives are handled by the
Python stdlib and include an extra `.cmf` (Casio format) and `.fmc`
(keyboard light guide) alongside the `.mid`.

The 6 `LK*SB*` entries are per-keyboard "internal-song packs" that
bundle other individually-downloadable songs, so the unique MIDI count
is **703**.

### Requirements

- Python 3.6+
- No external Python dependencies (`7z` / `p7zip` needed for `.lhc` extraction)

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
