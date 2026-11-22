# プロトコルの詳細

popIn Aladdin を制御する 2 系統のプロトコルと、この API がそれをどう使うかをまとめます。

- **UPnP/DLNA MediaRenderer** (標準仕様、Platinum 実装): 再生状態・音量・メディア URL のキャスト
- **独自プロトコル** (popIn 独自の TCP と、XGIMI GMSDK 由来の UDP): ライト・キー入力・文字入力・音声コマンド・deeplink・デバイス情報・スクリーンショット・電源断・デバイスの発見

実機の UPnP のフレンドリ名は `Aladdin 2` です。

## 動作の確認状況

独自プロトコルは、公式スマートフォンアプリ Aladdin X (`cc.popin.aladdin.assistant` 3.6.25、旧 popIn Aladdin) の静的解析で復元したものです。

- 実機での動作が確認されているもの ([kmaehashi/popin-aladdin-light](https://github.com/kmaehashi/popin-aladdin-light) の実測): ライト、方向キー、`back` `menu` `vol_up` `vol_down` `power`、文字入力、音声コマンド、ping。
- 静的解析だけで、実機 (popIn Aladdin 2) では未確認のもの: `/api/remote/version`・`/api/remote/album`・`/api/remote/apps/{package}`・`/api/remote/device`・`/api/discover`・`/api/deeplink`・`/api/memory/free`・`/api/capture`・`/api/power/off`、`/api/key` の `focus_*` `home_long` `menu_long` `settings` `netflix` `youtube` `prime_video` `custom*`。

## UPnP/DLNA MediaRenderer

```
GET  http://<host>:1481/                              … UPnP device description
POST http://<host>:1481/<Service>/<UDN>/control.xml   … SOAP コントロール
```

device description から各サービスの `controlURL` を解決し、SOAP でアクションを呼びます。
UDN と controlURL は MAC アドレス由来で機体ごとに固定なので、device description はプロセスの生存中キャッシュします。
公開サービスは次の 3 つです。

| サービス              | 主なアクション                                                                                                                     |
| --------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| **AVTransport**       | GetTransportInfo / GetPositionInfo / GetMediaInfo / Play / Pause / Stop / Next / Previous / Seek / SetAVTransportURI / SetPlayMode |
| **RenderingControl**  | GetVolume / SetVolume (0..100) / GetMute / SetMute                                                                                 |
| **ConnectionManager** | GetProtocolInfo                                                                                                                    |

## 独自プロトコル

アプリは popIn 独自の TCP プロトコルと、XGIMI 製プロジェクター用の制御 SDK (GMSDK、`com.xgimi.gmsdk`) の UDP プロトコルを併用しています。
定数の一部は kmaehashi/popin-aladdin-light (MIT) の実測とも一致します。

**認証について**: PIN・トークン・ペアリングによる認証はどのチャネルにもありません。
アプリは接続時に TCP の Version ハンドシェイク (クライアントの UUID を送る) を行いますが、デバイス側がそれを要求する証拠はなく、ライト・キー入力はハンドシェイク無しでも効きます (kmaehashi の実測)。
この API は照会系のコマンドだけ、アプリと同じ順序 (Version → 照会) で送ります。
アプリの SDK に含まれる `GMCheckAuthentication` (MD5 によるアプリ鍵検査) は呼ばれておらず、XGIMI 系機種向け TCP 13145 の認証コード (`AuthCode`) のやり取りもアプリ内で未使用です。

- **TCP 30913 (popIn 独自)**: 6 バイトヘッダ `struct '<IBB'` (uint32 payload 長 + uint8 フレーム種別 + uint8 JSON 種別) + JSON payload。1 接続に複数フレームを送れる。
  - フレーム種別 `0`: heartbeat (payload 無し、または `1`)。デバイスは 6 バイトの `0/0` 空フレームを返す。ping に使う。
  - フレーム種別 `3`: Version ハンドシェイク。`{"code": 10, "type": "JSON", "deviceId": "<uuid>", ...}` を送ると、同じ種別で `{"model", "device_name", "pid", "platform", "osVersion", "sdkInt", "totalSpace", "freeSpace", "lang", "country", "featureAccess": {...}, "capability": {"screenshot", "app_list"}, ...}` が返る (`/api/remote/version`)。
  - フレーム種別 `1`: 操作。JSON 種別で内容が決まる。
    - `7` RemoteControl `{"action": <code>}`: ライト (switch=31, brighter=32, darker=33, cooler=34, warmer=35, full=36, night=37, on=38, off=39, eco=40, sleep=41)。
      アプリの定数表にはキー操作用の code (1 shutdown, 2 screenshot, 3/4 volume, 5..18 キー, 19 clear memory, 22/23 focus, 42 settings, 51..55 ショートカット, 1001 child protect) もあるが、Aladdin 2 ではアプリがそれらを UDP 側で送るため、この API も UDP を使う。
    - `9` VoiceCommand `{"text": "...", "success": true}`: 音声コマンドの注入。
    - `10` IMECommand `{"text": "..."}`: フォーカス中の入力欄へ文字入力。
    - `15` DeeplinkInfo `{"deepLink": "..."}`: URL scheme / intent を開く (アプリ起動)。
    - `16` QueryAppInfo `{"pkgName": "..."}`: 同じ種別で `{"isInstalled", "versionCode", "versionName"}` が返る。
    - `2` Album: 同じ種別で `{"count", "list": [{"name", "size", "type"}], "freeSpace", "totalSpace", "lightVersion"}` が返る。
    - そのほかアプリが使う種別 (この API では未実装): `1` FileHead / `8` FileSendInfos (写真の転送。フレーム種別 `2` で本体を送る)、`3` RequestAlbumFile、`4` PlayImg / `5` StopImg / `6` DelImg (フォトメモリーの表示・削除)、`11`..`14` 誕生日 (holiday) 設定、`17` Karaoke、`19`..`21` Aladdin Poca の間接照明、`120` Response。
- **UDP 16735 (XGIMI GMSDK キー入力)**: ASCII データグラム。
  - 方向キー (押下 / 離上): `KEYSSTATUS:<key>+<1|0>` (home=35, up=36, right=37, down=38, ok=49, left=50)。離上時は全方向キーを離上した後、押したキーをもう一度離上する (kmaehashi の実測列)。
  - フォーカス調整: `KEYSSTATUS:253+1` → `KEYSSTATUS:253+0` (focus_plus)、`254` (focus_minus)。
  - HOME 長押し: `KEYSSTATUS:35+1` を 30 回送り、1 秒後に `KEYSSTATUS:35+0`。
  - 単発キー: `KEYPRESSES:<key>` (back=48, vol_down=114, vol_up=115, power (電源メニュー)=116, menu=139, menu_long=251, settings=300, netflix=301, youtube=302, prime_video=303, custom=304, custom_long=305)。
    SDK には 3D (252)・ゲームパッド (154..170, 244) の定数もあるが、Aladdin では使われていない。
  - 同じポートに `TOUCHEVENT:<dx>+<dy>` (エアマウス) も送れる。この API では未実装。
- **UDP 16750 (XGIMI GMSDK JSON コマンド)**: `{"action": 20000, "msgid": "2", "controlCmd": {"mode": M, "type": T, "time": 0, "delayTime": 0}}`。
  応答はクライアントの UDP 16751 に JSON で届く (アプリはこのポートに bind して送受信する)。
  - mode 9 / type 1: スクリーンショット → `{"action": 30235, "imagePath": "http://%s..."}` (`%s` はデバイス IP)。
  - mode 9 / type 2: メモリ解放 (応答無し)。
  - mode 32: 実行時情報 → `{"action": 30410, "deviceName", "deviceMode", "deviceApp", "packageApp", "runtime", ...}`。
  - mode 6 / type 0: 電源断 (アプリの電源ボタン長押し)。
  - この API では未実装: type 3 + `time` (オフタイマー)、mode 3 / 4 (3D・画質モード)、mode 2 + `zoomfocus` (フォーカス値指定)、mode 5 + `data` (音声コマンド)、mode 7 / type 3 (アプリ一覧)、action 30200 + `customPlay` (URL 再生)。
  - action 10000 (接続) / 10002 (heartbeat) / 9998 (UDP 16752 へのブロードキャスト検索) も SDK にあるが、コマンドの前提条件ではない ([Home Assistant の XGIMI 実装](https://github.com/manymuch/Xgimi-4-Home-Assistant)も接続無しで送る)。
- **UDP 8100 (発見)**: `"aladdin" + 0x14` を 1024 バイトに詰めてブロードキャストすると、デバイスが `"aladdin" + 種別 1 バイト + 長さ + JSON` で応答する。
  長さは種別 17 なら 1 バイト、19 / 21 なら big-endian 4 バイト。
  JSON は `{"success": true, "data": {"ipAddress", "model", "name", "pid", "mac", "version", "zipcode", "isConnected"}}`。

デバイスは他にも AirPlay (7000/7100) や AndServer (7434) を公開していますが、アプリのコードに 7434 へのアクセスは見つからず、この API の対象外です。
XGIMI 系機種 (Aladdin Marca 等) 向けの TCP 13145 (壁面補正) と UDP 16737 (タッチマウス) も対象外です。
