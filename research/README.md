# research/ — Casio独自フォーマットのリバースエンジニアリング

このフォルダは、本体の **SMF抽出ツール**（`casio_smf_extract.py` / `casio_*_download.py`）
とは別に、`.zip` ダウンロードに同梱される Casio 独自フォーマットの解析資料を置く場所です。

再生用の標準MIDIは同梱の `.mid` で既に手に入るため、ここでの解析対象は
**`.mid` には無い付加情報**（レッスン制御・運指ガイド）に絞っています。

| ファイル | 内容 |
|---|---|
| `CMF_FORMAT.md` | `.cmf`（Casio Music File Format）コンテナ仕様。674曲で検証済み。 |
| `casio_cmf_parse.py` | `.cmf` コンテナ構造のダンプ／検証ツール。 |
| `FMC_FORMAT.md` | `.fmc`（運指ガイド）解析メモ。レコード形式は判明、ボディ暗号化が未解決。 |
| `SOUND_ENGINE.md` | 音源解析。合成音源のためサンプルROM無し。録音にはAndroid実行が必要。 |

## メモ

- **`.cmf` → SMF 変換は本体ツールと冗長**：同梱 `.mid` が既に完全な再生用SMF
  （例: Birthday は .mid が22トラック/6219ノート、.cmf は17トラック固定でより小さい）。
  CMF の固有価値はレッスン制御（`channel+5` 符号化、伴奏ミュート、音色マップ）にある。
- **`.fmc`（運指ガイド）解析中**：`casi` マジック + バージョン。ボディは高エントロピー
  （圧縮/暗号化）。パーサーは `libsssg.so` の `read_Fingering`（fread でレコード読み込み、
  指番号は `finger+5` で格納）。
