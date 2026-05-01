# casio-mobilesongbank-midi-extractor

**Casio MobileSongBank** アプリ (`jp.co.casio.MobileSongBank`) の APK に内蔵された楽曲データを標準MIDIファイル (SMF Format 1) として一括抽出するツールです。

[English follows Japanese]

---

## 概要

Casio のキーボード連携アプリ MobileSongBank の APK には、LK-511/512/515/520/530 向けの内蔵曲データが `InternalSongsData*.bin` という形式でバンドルされています。各バイトにビット置換スクランブルが施されていますが、逆算したテーブルを適用することで標準MIDIファイルとして取り出せることがわかりました。

- **対象曲数**: 5データセット × 200曲 = **1,000曲**
- **出力形式**: SMF Format 1（22トラック前後、480 TPQ）
- **収録内容**: J-POP・クラシック・童謡など幅広いジャンル
- **外部ライブラリ**: 不要（Python 標準ライブラリのみ）

---

## 使い方

### 1. APK を取得・解凍する

[APKPure](https://apkpure.com/) などから `jp.co.casio.MobileSongBank` の APK をダウンロードし、ZIP として展開します。

```bash
cp jp.co.casio.MobileSongBank.apk msb.zip
unzip msb.zip -d msb_extracted/
```

`msb_extracted/assets/` の中に `InternalSongsData*.bin` と `sql/SongDB.sqlite3` が含まれていれば準備完了です。

### 2. スクリプトを実行する

```bash
python3 casio_smf_extract.py <assets_dir> [output_dir]
```

**例:**

```bash
python3 casio_smf_extract.py ./msb_extracted/assets ./casio_midi
```

**出力:**

```
SongDB: 1000 エントリ読み込み完了
  default :  200 曲
  LK512   :  200 曲
  LK515   :  200 曲
  LK520   :  200 曲
  LK530   :  200 曲

合計: 1000 曲を casio_midi/ に出力
ZIP: casio_midi.zip (4210 KB)
```

出力ディレクトリ構成:

```
casio_midi/
  default/
    001AC_Doraemon.mid
    002AC_UtiageHa.mid
    ...
  LK512/
    001AC_LemonYon.mid
    ...
  LK515/ LK520/ LK530/
casio_midi.zip
```

---

## 動作原理（リバースエンジニアリング詳細）

### ファイル構造

`InternalSongsData*.bin` の先頭 `0x640` バイト（200曲 × 8バイト）がインデックス領域です。各エントリは以下の構造を持ちます：

```
[データ領域内オフセット: uint32 LE][データサイズ: uint32 LE]
```

実際のデータ開始位置 = `0x640 + offset`。

### ビット置換スクランブル

ネイティブライブラリ `libsssg.so` の `read_InternalSongData` 関数 (`VA: 0x94fd8`) を ARM64 逆アセンブルし、各バイトへの **ビット置換テーブル** を解析しました：

```python
TABLE = [5, 2, 3, 7, 1, 0, 6, 4]
# bit i of input → bit TABLE[i] of output
```

このテーブルで全バイトをデコードすると `MThd`（標準MIDIマジック）が現れます。

```python
# 全256バイトの変換テーブルを事前展開（高速化）
_DECODE_TABLE = bytes(
    sum(((b >> i) & 1) << TABLE[i] for i in range(8))
    for b in range(256)
)

def decode_raw(raw: bytes) -> bytes:
    return bytes(_DECODE_TABLE[b] for b in raw)
```

### 検証

ドラえもん (Song 0, `001AC_Doraemon.mid`) の例:

| 項目 | 値 |
|------|-----|
| フォーマット | SMF Format 1 |
| BPM | 160 |
| TPQ | 480 |
| トラック数 | 22 |
| メロディ冒頭 | B4 B4 C#5 B4 G#4 F#4 E4 ... |

---

## 動作環境

- Python 3.6 以上
- 外部ライブラリ不要

---

## 注意事項

- 抽出した MIDI ファイルに含まれる楽曲は各著作権者が権利を持ちます。個人的な研究・学習目的以外での使用には注意してください。
- このツールは **リバースエンジニアリング研究** の成果です。Casio の公式サービスとは無関係です。
- APK の入手・使用は利用者の責任において適法に行ってください。

---

---

## Overview (English)

This tool extracts all built-in songs from the **Casio MobileSongBank** app APK (`jp.co.casio.MobileSongBank`) as standard MIDI files (SMF Format 1).

### How it works

The `InternalSongsData*.bin` files in the APK assets contain MIDI data scrambled with a **bit-permutation** applied to every byte. By reverse-engineering `libsssg.so` (ARM64) at `read_InternalSongData` (`VA: 0x94fd8`), the permutation table was recovered:

```
TABLE = [5, 2, 3, 7, 1, 0, 6, 4]
```

After decoding, each song is a valid SMF Format 1 MIDI file.

### Quick start

```bash
# Extract APK
unzip jp.co.casio.MobileSongBank.apk -d msb/

# Run extractor
python3 casio_smf_extract.py msb/assets output_midi/
```

### Output

1,000 songs across 5 datasets (default / LK512 / LK515 / LK520 / LK530), each a proper multi-track MIDI at 480 TPQ.

### Requirements

- Python 3.6+
- No external dependencies

### Disclaimer

Extracted MIDI files are copyrighted by their respective owners. This tool is for **personal research and archival purposes only**. Obtain APKs only through legitimate means.

---

## ライセンス / License

MIT License — see [LICENSE](LICENSE)
