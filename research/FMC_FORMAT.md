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

## 未解決：ボディが暗号化されている

`offset 7` 以降は全256バイト値がほぼ均等分布の**高エントロピー**。
上記 10 バイトレコードをそのまま当てはめても健全な値（note 0–127 / finger 1–5 /
時刻単調増加）にならず、**復号層がある**ことが確定。

- `read_Fingering` 自体は `FILE*` に対し素の `fread` を行うだけ → 復号は
  ファイルを開いて `read_Fingering` に渡す**前段**で行われている。
- `read_Fingering` への直接 `BL` 命令が `.text` 全体に見つからない →
  関数ポインタ経由で呼ばれており、ローダー（復号を含む）の特定には
  ポインタテーブル/vtable の追跡が必要。
- `libsssg.so` に `decrypt`/`aes`/`xor`/`lzh` 等のシンボルは無く、
  独自ルーチンと推定。

### 次にやるなら
1. `.fmc` を開く `fopen`／ローダー関数を特定（`cExtendedSongPathFmc`,
   `extendedSongNameFmc`, `proc_GetFingering`, `FingerGuideManager_nUpdate` 周辺）。
2. その関数内の復号ループ（XOR鍵 / バイト置換 / 簡易ストリーム暗号）を解析。
3. 復号後に上記 10 バイトレコードを検証（同梱 `.mid`/`.cmf` の音符と時刻照合）。

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
