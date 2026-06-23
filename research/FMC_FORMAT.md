# FMC (Casio 運指ガイドデータ) — 解析メモ

CASIO MobileSongBank の `.fmc` ファイル。`.zip` ダウンロードに `.mid` / `.cmf`
とともに同梱され、Casioキーボードの**運指ガイド（どの指で弾くか）**を保持する。
`.mid` には無い情報なので、解読できれば固有価値がある。

解析対象: `libsssg.so` (ARM64) の `read_Fingering`（VA 0x8bdf0）ほか。

---

## ヘッダ

```
offset 0 : "casi"          マジック (63 61 73 69)
offset 4 : version 3 bytes  例: 01 00 00 (旧) / 01 01 00 (新)
offset 7 : ...              以降は高エントロピー領域（下記）
```

## レコード構造（復号後・`read_Fingering` の逆アセンブルより確定）

`read_Fingering` は `fread` で 1 レコードずつ読み、メモリ上のノートイベント連結リスト
（ノートは構造体、time=offset 8, note=offset 1, finger=offset 0x19）と
時刻＋ノート番号で突き合わせて運指を割り当てる。

1 レコード = **10 バイト**：

```
timestamp : u64 LE  (8 bytes) — 絶対 tick
note      : u8      (1 byte)  — ノート番号
finger    : u8      (1 byte)  — 指番号 (1–5)
```

レコードは **左手チャンネル → 右手チャンネル** の順に並ぶ
（`get_LeftHandChannel` / `get_RightHandChannel` で対象チャンネルを取得）。
ノート構造体への格納時、指番号は内部表現で `finger+5` に変換される
（CMF の `channel+5` と同じ Casio 流儀）。

---

## ボディは「暗号化」ではなく独自圧縮（特定済み）

`offset 7` 以降は全256バイト値がほぼ均等分布の**高エントロピー**で、生の 10 バイト
レコードを当てても健全な値にならない。標準 zlib/bz2/lzma でも展開不可。
→ 当初は暗号化を疑ったが、`libsssg.so` の解析で **独自圧縮**と判明。

### 圧縮方式：BlockSort(BWT) + MTF + ZLE + RangeCoder

`libsssg.so` の `decode()`（VA 0x73220）が展開本体で、パイプラインは：

```
init_range_coder_global → range_decode → mtf_decode → blocksort_decode(逆BWT)
                          （ブロック単位でループ、ブロックヘッダは fgetc で読む）
```

バイナリ内文字列 **`"BlockSroting and RangeCoder Compressor Sample Program ver 2.0"`**
（"Sroting" は原典のタイポ）が決定的な指紋。これは「お気楽 Python プログラミング」
（M.Hiroi）の **ブロックソート法サンプル `bsrc1.py`**（BlockSort + MTF + ZLE +
RangeCoder）がベース。参照: https://www.nct9.ne.jp/m_hiroi/light/pyalgo49.html

関連シンボル: `range_decode` `range_encode` `init_range_coder_global`
`mtf_decode` `mtf_encode` `blocksort_decode` `blocksort_encode` `rle_decode`
`decode` `decode_file`（`exit()`を呼ぶ開発用ハーネス）。

### コンテナ形式（参照実装より）

```
size   : u32 BE  展開後の総バイト数
top    : u32 BE  逆BWTのプライマリインデックス
r_size : u32 BE  RLE/ZLE後のデータ長
... RangeCoder 圧縮ストリーム ...
```

逆BWT（分布数えソート）:
```
count[256]; for b in buff: count[b]++
累積和 count
for x in range(size-1,-1,-1): c=buff[x]; count[c]--; idx[count[c]]=x
x=idx[top]; for _ in size: out(buff[x]); x=idx[x]
```

### 残り作業（最後の一押し）
- Casio版 RangeCoder の定数（TOP/BOTTOM・正規化）を `range_decode` /
  `init_range_coder_global` の逆アセンブルで確定し、参照実装と突き合わせる。
- `decode()` のブロックヘッダ framing（fgetc 列）を確定。
- 展開後に 10 バイトレコードを検証（同梱 `.mid`/`.cmf` の音符・時刻と照合）。
- 検証できたら `casio_fmc_decode.py`（展開→運指 CSV/JSON 出力）を作成。

---

## 関連シンボル（libsssg.so）

```
read_Fingering            運指レコード読み込み（本体）
proc_GetFingering         運指取得処理
detect_FingeringType      運指タイプ判定（前後ノートのコスト計算）
doFingeringCostTableFwd   運指コストテーブル（順方向）
doFingeringCostTableRev   運指コストテーブル（逆方向）
get_LeftHandChannel       左手チャンネル
get_RightHandChannel      右手チャンネル
get_JustFinger / key_fingering / fingeringtable
```
