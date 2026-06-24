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

### コンテナ形式（バイナリ解析で確定・ファイルサイズで検証済み）

Casio 版は参照と異なり **`casi` ヘッダ + ブロック型**：

```
"casi"   4 bytes  マジック
version  1 byte
type     1 byte   0 = RLEなし / 非0 = rle_decode(n=7) を適用
top      3 bytes BE  逆BWTのプライマリインデックス
r_size   3 bytes BE  RangeCoder 圧縮データのバイト長
data     r_size bytes
```

検証: Birthday = 12バイトヘッダ + r_size 15661 = **15673**（実ファイルサイズ一致）。
SBA00599 = 12 + 23511 = **23523**（一致, type=1）。

### 展開パイプライン（確定）

```
range_decode(Freq012m, EOS=256) → [type≠0 なら rle_decode(n=7)]
→ mtf_decode → 逆BWT(top)
→ 平文 = 10バイトレコード [u64 LE time][u8 note][u8 finger 1..5]
```

- **RangeCoder**: M.Hiroi pyalgo36 版（`MIN_RANGE=0x1000000`, SHIFT=24, キャリー型）。
  バイナリの正規化定数 `0xffffff` と一致。**算術は検証済み**。
- **終端**: シンボル **256 が EOS マーカー**（`range_decode` が 0x100 で停止）。
- 逆BWT（分布数えソート）:
  ```
  count[256]; 各バイトを集計 → 累積和
  for x in range(size-1,-1,-1): c=buff[x]; count[c]--; idx[count[c]]=x
  x=idx[top]; for _ in size: out(buff[x]); x=idx[x]
  ```

実装: [`casio_fmc_decode.py`](casio_fmc_decode.py)（framing・RangeCoder・逆BWT・
パイプライン全段を実装、実ファイルで動作）。

### 残り作業（最後の一押し — 適応モデルの定数）

展開器はパイプライン全段が動くが、**適応モデルの各コンテキスト定数が未確定**のため
RangeCoder が徐々にズレ、BWT 後がまだ有効レコードにならない（Birthday: 4517レコード中
有効101）。`libsssg.so` は**混合法**（`mix_012_frequency` / `mix_first_frequency` /
`select_second_frequency` = Freq012m）を使い、各コンテキストの `(inc, limit)` は
`init_frequency_table` が設定。`update_frequency` の解析で構造（16bitカウント,
GR=16グループ, inc/limit による rescale）は参照の `Freq` と一致を確認済み。

→ 残るは `init_frequency` / `init_frequency_table` の各呼び出し引数（コンテキスト毎の
`size, inc, limit`）と `mix_012_frequency` の混合式をビット完全一致で抽出すること。
これが揃えば RangeCoder が同期し、10バイトレコードが復元される（同梱 `.mid`/`.cmf` の
音符・時刻で照合可能）。
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
