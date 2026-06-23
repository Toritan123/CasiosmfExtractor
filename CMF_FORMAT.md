# CMFF (Casio Music File Format) — リバースエンジニアリング仕様

CASIO MobileSongBank の `.cmf` ファイルを解析した結果。
`.zip` 形式でダウンロードされる曲（674曲）に `.mid` / `.fmc` とともに同梱される、
Casioキーボードのレッスン機能用の独自楽曲フォーマット。

解析対象: `libsssg.so` (ARM64) のエクスポートシンボルおよび 674 ファイルの実データ。
コンテナ構造は **674/674 ファイルで検証済み**（全ファイルが末尾までぴったり構造一致）。

---

## コンテナ構造

```
offset 0   : "CMFF"          マジック (4 bytes)
offset 4   : header_len      uint32 LE   — offset 8 から最初の TRAK までのバイト数
offset 8   : ヘッダ本体       バージョン/書式タグ + 固定長タイトルフィールド
offset 8+L : TRAK チャンク × 17  (16 MIDIチャンネル + 1 システムトラック)
```

### ヘッダ本体（タグバイト列）

`get_CmfHeader`（実体は Seq2Cmf エンコーダのヘッダ生成）が書き込む定数列：

```
'C' 'M' 'F' 'F' '!' 03 04 05 ...  (バージョン/書式タグ)
<タイトル>  ASCII、半角スペースで右パディング
06 11 07 04 08 00 09 01 0a 84 0b 00 0c 01 0f 00 00 10 01 ...  (メタタグ群)
```

タイトルはヘッダ本体内の最長 ASCII 連続列として抽出可能（全674曲で成功）。

### TRAK チャンクヘッダ（12 bytes）

```
"TRAK"            4 bytes  マーカー
00 ab 00 00       4 bytes  定数 (0x0000ab00 — トラック種別/フラグと推定)
length            uint32 LE  ペイロードのバイト数
payload[length]   イベントストリーム（次チャンクは直後に連続）
```

全曲が **正確に 17 トラック**。最後のチャンクのペイロード終端がファイル末尾と一致
（674/674 で余りバイト 0）。

---

## イベント符号化プリミティブ

`libsssg.so` の逆アセンブルから判明。

### トラックコマンド（`get_CmfTrackCommand`, VA 0x73efc）

ステータス値を 2 バイトに分割。MIDI 同様、コマンドの先頭バイトは bit7 立て：

```
buffer[pos]   = (cmd & 0x7f) | 0x80
buffer[pos+1] =  cmd >> 7
```

デコード時: `byte & 0x80` ならコマンド開始、`cmd = (byte & 0x7f) | (next << 7)`。

### デルタタイム（`get_CmfDeltaTime`, VA 0x73f1c）

**リトルエンディアンの 7 ビット可変長量 (VLQ)**。標準 MIDI とは逆で LSB が先頭、
各バイトの bit7 が「後続バイトあり」を示す：

```
value = b0 & 0x7f
if b0 & 0x80: value |= (b1 & 0x7f) << 7
if b1 & 0x80: value |= (b2 & 0x7f) << 14
...
```

デルタが内部上限 (0x0fffffff) を超える場合は `0x7f` マーカーで時間リセットを挿入。

---

## イベント種別（`libsssg.so` シンボルより）

| シンボル | 意味 |
|---|---|
| `get_CmfNoteOn` | ノートオン |
| `get_CmfControlChange` | コントロールチェンジ |
| `get_CmfProgramChange` | プログラムチェンジ（音色） |
| `get_CmfPitchBend` | ピッチベンド |
| `get_CmfChannelPressure` | チャンネルプレッシャー |
| `get_CmfDrumPartBankSelect` | ドラムパートのバンクセレクト |
| `get_CmfMidiTrack` | 通常 MIDI トラック |
| `get_CmfSystemTrack` | システムトラック（テンポ/拍子等） |
| `get_CmfStepLessonAccompOffTrackMute` | **ステップレッスン時の伴奏トラックミュート** |

最後の `StepLessonAccompOffTrackMute` が CMF 固有の付加価値で、
Casioキーボードの「ステップアップレッスン」機能用に
「どのトラックを消すか（片手練習など）」のレッスン制御情報を保持している。

---

## .mid との関係

同梱の `.mid` は再生用の標準 MIDI（既にデコード済み・即再生可能）。
`.cmf` はその元データで、上記レッスン制御メタデータを追加で含む。
**再生だけなら `.mid` で十分**。`.cmf` の独自価値はレッスン情報（運指補助や
伴奏ミュート指定）にある。

---

## ツール

- `casio_cmf_parse.py` — コンテナ構造のダンプ／全ファイル検証
  ```bash
  python3 casio_cmf_parse.py song.cmf          # 構造ダンプ
  python3 casio_cmf_parse.py --scan extracted/ # 全 .cmf を検証
  ```

## 未解析（次のステップ）

- イベントストリーム本体の完全デコード（→ レッスン運指・コードの抽出）
- `.fmc`（運指ガイド、`casi` マジック＋暗号化らしきデータ）の解読
- 17 トラックの役割マッピング（システムトラックの位置特定）
