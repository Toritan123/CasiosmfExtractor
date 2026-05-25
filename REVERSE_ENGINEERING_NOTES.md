# リバースエンジニアリングメモ

## 解析対象

| アプリ | パッケージ名 | ネイティブライブラリ |
|--------|-------------|-------------------|
| MobileSongBank | `jp.co.casio.MobileSongBank` | `lib/arm64-v8a/libsssg.so` (約1.5MB) |
| ChordanaPlay | `jp.co.casio.chordanaplay` | 同上 (共通ライブラリ) |
| CASIO MUSIC SPACE | `jp.co.casio.CasioMusicCity` | 同上 (共通ライブラリ) |

3アプリとも同じ `libsssg.so` を共有しており、同一のスクランブル方式を使用。

---

## ファイル構造

### インデックス領域

`.bin` ファイルの先頭に各曲へのインデックスが並ぶ。

```
各エントリ: 8 バイト
  [0..3] データ領域内オフセット (uint32, little-endian)
  [4..7] データサイズ          (uint32, little-endian)
```

実際のデータ開始位置 = `(曲数 × 8) + オフセット`

**曲数はファイルによって異なる（自動検出が必要）:**
- オフセットが単調増加かつサイズがファイル範囲内であるエントリを数える

### データ領域

インデックス直後から、各曲のスクランブルされたデータが連続する。

---

## ビット置換スクランブルの解析

### 解析箇所

`libsssg.so` の `read_InternalSongData` 関数:
- **アーキテクチャ**: ARM64
- **仮想アドレス**: `0x94fd8`
- **処理**: `ubfx` 命令でビットを個別抽出し、グローバルテーブル `[x26, #0x338]` で各ビットを新位置にシフトして OR で結合

### テーブルの特定

各バイトの全8ビットを個別に追跡し、以下の置換テーブルを解析:

```
TABLE = [5, 2, 3, 7, 1, 0, 6, 4]
# 入力バイトのビット i → 出力バイトのビット TABLE[i]
```

全 40320 通りの置換を総当たりし、デコード結果が `MThd` または `CMFF` マジックになるものを選出して確認。

### 実装

```python
TABLE = [5, 2, 3, 7, 1, 0, 6, 4]

# 全256バイトの変換テーブルを事前展開（処理高速化）
_DECODE_TABLE = bytes(
    sum(((b >> i) & 1) << TABLE[i] for i in range(8))
    for b in range(256)
)

def decode_raw(raw: bytes) -> bytes:
    return bytes(_DECODE_TABLE[b] for b in raw)
```

### 検証例

`InternalSongsData.bin` (MobileSongBank) Song 0 の先頭4バイト:
- デコード前: `66 c2 45 43`
- デコード後: `4d 54 68 64` = `MThd` ✓

`InternalSongsData.bin` (ChordanaPlay) Song 0 の先頭4バイト:
- インデックス領域サイズ: `50 × 8 = 0x190` バイト
- データ開始位置: `0x190`
- デコード後: `4d 54 68 64` = `MThd` ✓

---

## デコード後の MIDI ファイル仕様

| 項目 | MobileSongBank | ChordanaPlay |
|------|---------------|-------------|
| フォーマット | SMF Format 1 | SMF Format 1 |
| TPQ | 480 | 480 |
| トラック数 | 5〜26（曲依存） | 1（メロディのみ） |
| 収録ジャンル | J-POP・アニメ等 | クラシック・民謡 |

---

## CMF フォーマット（`InternalSongsDataCmf*.bin`）

MobileSongBank APK には同じ曲データの別形式として CMF 版も同梱されている。同じビット置換でデコードすると `CMFF` マジックで始まる Casio 独自形式。

### CMF ヘッダー

```
Offset  Size  Value     説明
0x00    4     "CMFF"    マジック
0x04    1     0x25      バージョン
0x05    3     00 00 00  予約
0x08    2     03 04     フォーマット情報
...
```

### TRAK ブロック

```
"TRAK" [4] + total_size [4 LE] + event_data_size [4 LE] + イベントデータ
```

### CMF イベント形式

```
[delta_time: VLQ]
  次バイト < 0x80 → Note ON:
    [note(0-127)][ch+5(1byte)][velocity][duration: VLQ]
  次バイト >= 0x80 → CMD(2バイトエンコード):
    [cmd_lo | 0x80][cmd_hi]  # cmd = cmd_lo | (cmd_hi << 7)
    [ch+5(1byte)]
    [params...]              # CMD値に応じた長さ
```

主要 CMD:
- `0x84`: Program Change (params: bank, prog)
- `0x92`: Pitch Bend (params: hi, lo)
- `0x93` 等: Control Change

**用途**: CMF 版はキーボード本体への転送用（`nTransferSongData`）。SMF 版はアプリ内再生・楽譜表示用。CMF 版のサイズは SMF 版の約 63%。

---

## SongDB の構造

`assets/sql/SongDB.sqlite3` の `songs` テーブル:

| カラム | 内容 |
|--------|------|
| `file_name` | 曲の識別名（例: `001AC_Doraemon`） |
| `title` | 曲タイトル（日本語） |
| `artist` | アーティスト名 |
| `db_index` | 各データセットでのインデックス番号（スペース区切り、`n`=未収録、`-`=追加DL曲） |
| `iap_contents_id` | アプリ内課金コンテンツID |

`db_index` の順序はデータセットの追加順に対応し、バージョンアップで列数が増加する（旧: 5値、新: 6値）。

---

## 追加ダウンロード曲について

SongDB に `db_index = '-'` で登録された曲は追加購入曲。

ダウンロードエンドポイント:
```
POST https://mobilesongbank.com/dlfprcheck/dlforproducts.php
```

必要なパラメータ:
- `uniqid`: デバイス固有ID（`libsssg.so` 内 `nGetUniqID873Thread` が生成）
- `signature`: App Store / Google Play の購入レシート署名

いずれもデバイス・購入アカウントに紐付いており、**実機なしの自動ダウンロードは不可能**。

購入済みの場合、ダウンロードされた曲データはアプリのサンドボックス内（iOS: `Library/Application Support/` など Documents 外）に保存され、ファイル形式・スクランブル方式は内蔵曲と同一と推測される。

---

## CASIO MUSIC SPACE — Web API ダウンロード（認証不要）

CASIO MUSIC SPACE (`jp.co.casio.CasioMusicCity`) では、SP/DP どちらの曲も
Casio が運営する公開エンドポイントから **認証なし** で取得できる。

```
POST https://musicapp.casio.jp/dlmusicdata/dlmusicdata_android.php
Headers:
  User-Agent: Android
  Content-Length: <body length>
Body (raw UTF-8, key=value ではない):
  <file_id>.<ext>
```

- `<ext>` ∈ {`mid`, `mp3`, `pdf`, `txt`}
- 成功時: `Content-Type: application/force-download` で本体を返す
- 失敗時（不正な file_id 等）: HTTP 200 + 0 バイト（404 ではない）

### 解析箇所

`classes.dex` の `jp.co.casio.chordanaplay.lib.Manager.HTTPConnectionManager`:

- `HTTPrequestDL(name, ext, dstDir)` がエントリポイント
- 内部 `HttpPostTask.doInBackground` で次のリクエストを組み立てる:

  ```java
  httpURLConnection.setRequestMethod("POST");
  httpURLConnection.setRequestProperty("User-Agent", "Android");
  httpURLConnection.setRequestProperty("Content-Length",
      String.valueOf(fileName.length()));
  outputStream.write(fileName.getBytes("UTF-8"));  // body = "<file_id>.<ext>"
  ```

### cms_songs.db との対応

| カラム | 内容 |
|--------|------|
| `file_id` | API での識別子（例: `ML001_Nocturne`, `EA001_PCon1T_1`） |
| `title_en` / `title_ja` / `title_cn` | 多言語タイトル |
| `songs_collection` | コレクション名（ミュージックライブラリー等） |
| `data_type` | `SP`=内蔵, `DP`=ダウンロード, `-`=見出し行 |

`data_type='SP'` の行は rowid 順で `InternalSongsData.bin` のインデックスと一致する
（先頭 50 件のみ bin に格納されており、残りは API 経由）。

### bin抽出 vs API取得は別データ

`ML001_Nocturne` 等の同じ file_id でも、bin から抽出した SP 版と
API からダウンロードしたフル版は md5 が一致しない:

- bin 版: 簡易MIDI（小さい、4トラック前後）— 内蔵キーボードの音源で簡易再生する用
- API 版: フルアレンジ（2〜10倍長い、伴奏トラック付き）— アプリ内 PCM 再生 + PDF 楽譜表示と同期

### Firebase 認証の試み（失敗）

`google-services-desktop.json` には Firebase 設定が同梱されているが、

- 匿名認証 (`identitytoolkit.googleapis.com/v1/accounts:signUp`) は
  `API_KEY_SERVICE_BLOCKED` で拒否される
- Storage 直接アクセス (`firebasestorage.googleapis.com/v0/b/casio-music-city.appspot.com/o/...`) も 404
- RTDB ルートも `Permission denied`

そもそも上記 `dlmusicdata_android.php` で全アセットが取れるため Firebase は不要。
