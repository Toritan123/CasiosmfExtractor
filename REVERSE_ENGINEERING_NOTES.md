# リバースエンジニアリングメモ

## 解析対象

- APK: `jp.co.casio.MobileSongBank`
- ネイティブライブラリ: `lib/arm64-v8a/libsssg.so` (約1.5MB)
- データファイル: `assets/InternalSongsData*.bin` (各約1.6MB)

---

## ファイル構造解析

### インデックス領域

各 `.bin` ファイルの先頭 **0x640バイト** (200 × 8バイト) がインデックス。

```
Offset  Size  Description
0x000   4     Song 0: data_offset (relative to 0x640)
0x004   4     Song 0: data_size
0x008   4     Song 1: data_offset
0x00C   4     Song 1: data_size
...
0x638   4     Song 199: data_offset
0x63C   4     Song 199: data_size
```

実際のデータ = `file[0x640 + data_offset : 0x640 + data_offset + data_size]`

---

## ビット置換の発見

### 解析箇所

`libsssg.so` の `read_InternalSongData` 関数:
- **仮想アドレス**: `0x94fd8`
- ARM64 命令: `ubfx` でビットを個別抽出し、グローバルテーブルで再配置

### テーブルの特定

候補を全40320通り試行し、デコード結果が `CMFF` / `MThd` マジックになるものを選出。

```python
TABLE = [5, 2, 3, 7, 1, 0, 6, 4]
# bit i of input → bit TABLE[i] of output
```

### 検証

`InternalSongsDataCmf.bin` Song 100 の先頭4バイト:
- 変換前: `70 66 52 52`
- 変換後: `43 4D 46 46` = `CMFF` ✓

`InternalSongsData.bin` Song 0 の先頭4バイト:
- 変換前: `4D 54 68 64` → 変換後: `4D 54 68 64` = `MThd` ✓  
  *(このファイルのmagicはすでに変換済みの値と一致)*

---

## MIDI ファイル仕様（抽出後）

| 項目 | 値 |
|------|-----|
| フォーマット | SMF Format 1 |
| TPQ (Ticks Per Quarter) | 480 |
| トラック数 | 5〜26 (曲により異なる) |
| トラック名例 | Melo, Melo_Finger, Obli A〜E, Drums, Bass, Key, GMReset, DemoMode, SystemEffect, MasterVolume, SongEnd, Phrase |

---

## CMF フォーマット（`InternalSongsDataCmf.bin`）

同じビット置換でデコードすると `CMFF` マジックで始まる Casio 独自フォーマット。

### CMF ヘッダー

```
Offset  Size  Value     Description
0x00    4     "CMFF"    マジック
0x04    1     0x25      バージョン?
0x05    3     000000    予約
0x08    2     03 04     フォーマット情報
0x0A    3     00 01 05  予約
0x0D    5     (title)   曲タイトル (スクランブル)
0x12    7     (spaces)  パディング
0x19+   n     key-value  属性ペア
...
```

### TRAK ブロック

```
Offset  Size  Description
0x00    4     "TRAK"    マジック
0x04    4     total_size (little-endian)
0x08    4     event_data_size (little-endian)
0x0C+   n     CMFイベントデータ
```

### CMF イベント形式

```
[delta_time: VLQ]
  if next_byte < 0x80:
    [note: 1byte] [ch5: 1byte] [velocity: 1byte] [duration: VLQ]
    # ch5 = MIDI ch + 5  (ch=0 → ch5=5)
  else:
    [cmd_lo|0x80: 1byte] [cmd_hi: 1byte]   # 2-byte VLQ CMD
    [ch5: 1byte]
    [params: N bytes]   # CMD値によって異なる
```

主要 CMD 値:
- `0x84`: Program Change (params: bank, prog)
- `0x92`: Pitch Bend (params: hi, lo)
- `0x93`, `0x8C`, `0xA9`, `0x8D`: Control Change

---

## SongDB の構造

`assets/sql/SongDB.sqlite3` の `songs` テーブル:

| カラム | 内容 |
|--------|------|
| `file_name` | 曲ファイル名 (例: `001AC_Doraemon`) |
| `title` | 曲タイトル |
| `artist` | アーティスト名 |
| `db_index` | 各データセットでのインデックス番号 (スペース区切り5値, `n`=未収録) |
| `iap_contents_id` | Google Play IAP コンテンツID |

`db_index` の並び順: `default LK512 LK515 LK520 LK530`

例: `"1 n n n n"` → default の1曲目、他のデータセットには未収録

---

## 追加ダウンロード曲について

SongDB に登録された602曲 (`db_index='-'`) は追加購入曲。

ダウンロードURL: `https://mobilesongbank.com/dlfprcheck/dlforproducts.php`

必要なパラメータ:
```
modelname=...&appname=...&localeid=...
&uniqid=<デバイス固有ID>  ← libsssg.so の nGetUniqID873Thread が生成
&signature=<Google Play 購入レシート署名>
&dltype=...&filename=...&json=...
```

`uniqid` はデバイス固有かつネイティブライブラリ内で生成されるため、**実機なしの自動ダウンロードは不可**。root済み端末でアプリデータから直接取得した `.bin` ファイルは同じビット置換でデコード可能と推測される。
