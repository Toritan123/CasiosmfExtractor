# Casio サウンドエンジン（音源）解析

MobileSongBank の楽器音の所在を調べた結論。**抜き出せる「楽器サンプルROM」は存在しない**。

解析対象: `libsssg.so` (ARM64) のシンボル・セクション・埋め込みデータ。

---

## 結論：サンプラーではなく合成音源

音源は `libsssg.so` 内に実装された Casio **AiX 系**のシンセエンジン
（文字列 `AiX` / `AppSoundSource` / `APP_BUILT_IN_SOUND` で確認）。
多数の WAV を持つサンプラー型ではなく、**コンパクトなテーブルから実行時に音を
合成するウェーブテーブル/パラメトリック音源**。したがって数MBのPCMバンクは無い。

### 埋め込みデータ（小さいパラメータROMのみ）

| シンボル | サイズ | 内容 |
|---|---|---|
| `rompcm`  | 6,912 B | PCM **ディスクリプタ**（オフセット/ループ点等。波形本体ではない） |
| `romtone` | 7,480 B | 音色定義の構造体配列 |
| `romenv`  | 3,140 B | エンベロープ（rate/level） |
| `ucCasioAccomp` | 147,048 B | 自動伴奏パターン（**音声ではない**） |

波形バッファ（`wavebuff` / `cWaveOfOneByte` / `wvbuf` 等）はいずれも **`.bss`＝
実行時生成**。`.bss` は約 59MB あるが、これは発音・エフェクトの作業メモリであり
静的なサンプルROMではない。

### APK に同梱される唯一の音声ファイル

`assets/fingerGuide/Count-1S.wav` … `Count-5S.wav`（レッスンのカウントイン音）のみ。
楽器音色の WAV は同梱されていない。

---

## 楽器音を得る唯一の方法：シンセ出力を録音する

サンプル抽出（静的）はできないため、**合成結果を録音**するしかない。
`libsssg.so` の駆動 API は以下（いずれも純 C 関数、JNI 不要）：

```c
void *h = createSssg(cfg);          // シンセ生成（malloc 0x130 のハンドル）
putmidiSxsg(h, midi_msg, ...);      // MIDIメッセージ投入（program change で音色選択 → note on）
                                    //   内部で sxgm_convert を呼ぶ
getwaveSxsg(h, out_buf, nframes);   // PCM を out_buf に描画（内部 sxlsi_get / sxmod_get）
allNoteOff(h); destroySxsg(h);
```

描画手順: `createSssg` → `putmidiSxsg`(program change) → `putmidiSxsg`(note on)
→ `getwaveSxsg` をループして PCM を集め、note off 後もリリース分を描画 → WAV 書き出し。

### 実行環境の制約（重要）

`libsssg.so` の DT_NEEDED は **すべて Android 専用**：

```
libOpenSLES.so  liblog.so  libandroid.so  libstdc++.so  libm.so  libc.so  libdl.so
```

→ macOS では ELF をロード不可。**Android 実機 / エミュレータ（NDK）でしか動かない。**
qemu-user・frida・adb・emulator が無い環境では実行不能。

録音を行うなら次のいずれか：
1. **実機でアプリを動かしてシステム音声を録音**（RE不要・最も確実・手動）。
2. **NDK ハーネスを書いて `libsssg.so` を駆動**（上記API）。要 `sxgm_convert` の
   MIDIメッセージ packing と `createSssg` 引数・出力フォーマットの追加解析。

---

## 関連シンボル

```
createSssg / createSxsg / destroySxsg   シンセ生成・破棄
putmidiSxsg / sxgm_convert              MIDI入力
getwaveSxsg / getwaveSssg / sxlsi_get   PCM描画
allNoteOff / put_AllNoteOff             全ノートオフ
rompcm / romtone / romenv               パラメータROM（埋め込み）
SetAppSoundSource                       音源切替
```
