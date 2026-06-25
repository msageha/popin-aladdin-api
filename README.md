# popIn Aladdin API

天井照明付きプロジェクター **popIn Aladdin**（実機の UPnP フレンドリ名は
`Aladdin 2`）のローカル UPnP/DLNA MediaRenderer を FastAPI + Pydantic で
ラップした REST サーバーです。クラウドを介さず、同一 LAN から再生状態や音量を
取得し、再生/一時停止/シーク/音量変更、任意メディア URL のキャスト（投影）などを
操作できます。

## 仕組み

popIn Aladdin は Android ベースの機器で、LAN 上に複数のサービスを公開しています
（AirPlay: 7000/7100、UPnP MediaRenderer: 1481、AndServer: 7434 ほか）。本 API は
本 API は2系統の制御面をラップします。

1. **UPnP/DLNA MediaRenderer**（`Platinum` 実装、標準仕様）— 再生制御・音量・キャスト
2. **独自 popIn/MAXHUB 制御プロトコル** — シーリングライト操作・プロジェクターの
   方向キー/ハードキー・オンスクリーンキーボード（文字）入力・音声コマンド

```
GET  http://<host>:1481/                         … UPnP device description
POST http://<host>:1481/<Service>/<UDN>/control.xml  … SOAP コントロール
TCP  <host>:30913   … 独自プロトコル（ライト・文字入力・音声）
UDP  <host>:16735   … 独自プロトコル（方向キー・ハードキー）
```

### 独自プロトコル

popIn Aladdin は内部的に MAXHUB（CVTE）のモバイル制御プロトコルを使っています。
公式アプリのライト操作・リモコン入力はこの経路です。

- **TCP 30913**: 6バイトヘッダ `struct '<IBB'`（uint32 ペイロード長 + uint8 `op1`
  + uint8 `op2`）＋ JSON ペイロード。
  - ライト: `op1=1, op2=7, {"action": <code>}`（switch=31, brighter=32, darker=33,
    cooler=34, warmer=35, full=36, night=37, on=38, off=39, eco=40, sleep=41）
  - 文字入力: `op1=1, op2=10, {"text": "..."}`
  - 音声: `op1=1, op2=9, {"text": "...", "success": true}`
  - ping: `op1=0, op2=0, payload=1` → 6バイトの null 応答
- **UDP 16735**: ASCII データグラム / JSON。
  - 方向キー（押下/離上）: `KEYSSTATUS:<key>+<1|0>`（home=35, up=36, right=37,
    down=38, ok=49, left=50）
  - ハードキー（単発）: `KEYPRESSES:<key>`（back=48, vol_up=115, vol_down=114,
    power=116, menu=139）
  - 保守コマンド: JSON `{"action": 20000, "controlCmd": {"mode": 9, "type": <1|2>,
    "time": 0}}`（type=2 メモリ解放, type=1 capture）、`{"action": 10002}`（UDP ping）

認証・ハンドシェイク・暗号化はありません。プロトコル定数は
[kmaehashi/popin-aladdin-light](https://github.com/kmaehashi/popin-aladdin-light)
（MIT）の解析に基づきます。

device description を取得して各サービスの `controlURL` を解決し、SOAP で
アクションを呼びます。UDN は MAC 由来で機体ごとに変わるため、パスを決め打ちせず
description から都度解決します。公開サービスは次の 3 つです。

| サービス | 主なアクション |
| --- | --- |
| **AVTransport** | GetTransportInfo / GetPositionInfo / GetMediaInfo / Play / Pause / Stop / Next / Previous / Seek / SetAVTransportURI / SetPlayMode |
| **RenderingControl** | GetVolume / SetVolume(0..100) / GetMute / SetMute |
| **ConnectionManager** | GetProtocolInfo |

> 認証はありません。LAN 内の誰でも読み書きできます。

デコード・SOAP 組み立ては `src/aladdin/soap.py`、通信と高レベル API は
`src/aladdin/client.py` にあります。

## セットアップ

`.env` に接続先を記載します（デフォルトのままでも可）。

```dotenv
POPIN_ALADDIN_HOST=http://172.16.1.113
UPNP_PORT=1481
DESCRIPTION_PATH=/
# 認証は不要だが参考用に保持できる（renderer では未使用）
USERNAME=
PASSWORD=
TIMEOUT=10
```

依存関係のインストール（`make setup` でも可）:

```bash
uv sync --extra test
```

実機のサービス・ポートを調べたいときは discovery スクリプトを実行します。

```bash
uv run python scripts/probe.py
```

## 構成

`src/` レイアウトの virtual プロジェクト（ビルドなし）。実行・テストは
`pythonpath=src` ／ `--app-dir src` ／ `PYTHONPATH=src` でパッケージを解決します。

```
src/
  aladdin/   デバイス制御クライアント（FastAPI 非依存・単体利用可）
             soap.py / client.py … UPnP/DLNA renderer
             remote.py            … 独自 popIn/MAXHUB 制御（ライト・キー・文字）
             exceptions.py
  api/       FastAPI Web 層: routes.py / schemas.py / service.py
  config.py  Settings（pydantic-settings）
  main.py    FastAPI アプリ
tests/       オフライン単体テスト（soap・client・remote・schemas）
scripts/     probe.py（ポートスキャン + device description + SCPD 列挙）
```

## 起動

```bash
make run   # = uv run uvicorn main:app --reload --app-dir src --host 127.0.0.1 --port 8000
```

- Swagger UI: http://127.0.0.1:8000/docs

### Docker

```bash
make build-image                       # docker build -t popin-aladdin-api:latest .
docker run --rm -p 8000:8000 --env-file .env popin-aladdin-api:latest
```

多段ビルド（`uv` ビルダ → `python:slim` ランナー、非 root 実行）。

## エンドポイント

| Method | Path                | 説明                                            |
| ------ | ------------------- | ----------------------------------------------- |
| GET    | `/api/health`       | サーバー状態と接続先                            |
| GET    | `/api/info`         | デバイス情報（friendly_name/model/UDN/services）|
| GET    | `/api/status`       | 集約状態（state/volume/mute/現在URI/位置）      |
| GET    | `/api/transport`    | 再生状態（state/status/speed）                  |
| GET    | `/api/position`     | 再生位置・トラック情報                          |
| GET    | `/api/media`        | 現在メディア情報（URI/duration）                |
| GET    | `/api/protocol-info`| 対応プロトコル（source/sink）                   |
| GET    | `/api/volume`       | 音量取得                                        |
| POST   | `/api/volume`       | 音量設定（0..100）                              |
| GET    | `/api/mute`         | ミュート状態取得                                |
| POST   | `/api/mute`         | ミュート設定                                    |
| POST   | `/api/play`         | 再生                                            |
| POST   | `/api/pause`        | 一時停止                                        |
| POST   | `/api/stop`         | 停止                                            |
| POST   | `/api/next`         | 次のトラック                                    |
| POST   | `/api/previous`     | 前のトラック                                    |
| POST   | `/api/seek`         | シーク（秒）                                    |
| POST   | `/api/play-mode`    | 再生モード設定                                  |
| POST   | `/api/cast`         | 任意メディア URL を投影・再生                   |
| GET    | `/api/remote/buttons` | 利用可能なボタン名一覧（light/key/key_stateless）|
| POST   | `/api/remote/ping`  | 独自プロトコル(TCP)の疎通確認                    |
| POST   | `/api/light`        | シーリングライト操作（`button` + `repeat`）     |
| POST   | `/api/key`          | 方向キー/ハードキー入力（`button` + `repeat`）  |
| POST   | `/api/keyboard`     | オンスクリーンキーボードへ文字入力（`text`）    |
| POST   | `/api/voice`        | 音声コマンドをテキストとして送信（`text`）      |
| POST   | `/api/memory/free`  | バックグラウンドアプリのメモリ解放              |
| POST   | `/api/capture`      | デバイスの capture コマンド送信                 |
| POST   | `/api/soap`         | 任意 SOAP アクションのパススルー（Set 系は `confirm` 必須） |

### 状態の取得例

```bash
curl http://127.0.0.1:8000/api/status
```

```json
{
  "state": "PLAYING",
  "status": "OK",
  "volume": 35,
  "mute": false,
  "current_uri": "http://192.168.1.50:8200/video/sample.mp4",
  "track_duration_seconds": 212.0,
  "position_seconds": 30.0
}
```

### 音量操作例

```bash
curl -X POST http://127.0.0.1:8000/api/volume \
  -H 'Content-Type: application/json' -d '{"volume": 40}'
```

### キャスト（投影）例

LAN 上から到達できるメディア URL を渡すと、DIDL-Lite メタデータを自動生成して
ロード・再生します。

```bash
curl -X POST http://127.0.0.1:8000/api/cast \
  -H 'Content-Type: application/json' \
  -d '{"uri":"http://192.168.1.50:8200/video/sample.mp4","upnp_class":"object.item.videoItem"}'
```

### ライト操作例

```bash
# 点灯 / 消灯
curl -X POST http://127.0.0.1:8000/api/light \
  -H 'Content-Type: application/json' -d '{"button":"on"}'

# 明るさを10段階上げる
curl -X POST http://127.0.0.1:8000/api/light \
  -H 'Content-Type: application/json' -d '{"button":"brighter","repeat":10}'
```

`button`: `switch` `brighter` `darker` `cooler` `warmer` `full` `night` `on`
`off` `eco` `sleep`

### 方向キー / リモコン入力例

```bash
# カーソルを下へ → 決定
curl -X POST http://127.0.0.1:8000/api/key -d '{"button":"down"}' \
  -H 'Content-Type: application/json'
curl -X POST http://127.0.0.1:8000/api/key -d '{"button":"ok"}' \
  -H 'Content-Type: application/json'
```

`button`: 方向キー `up` `down` `left` `right` `ok` `home` ／ ハードキー
`back` `menu` `vol_up` `vol_down` `power`

### キーボード（文字）入力例

```bash
curl -X POST http://127.0.0.1:8000/api/keyboard \
  -H 'Content-Type: application/json' -d '{"text":"hello world"}'
```

### 汎用 SOAP パススルー

読み取り（`confirm` 不要）:

```bash
curl -X POST http://127.0.0.1:8000/api/soap \
  -H 'Content-Type: application/json' \
  -d '{"service":"AVTransport","action":"GetTransportInfo","args":{"InstanceID":0}}'
```

書き込み（破壊的・`confirm` 必須）:

```bash
curl -X POST http://127.0.0.1:8000/api/soap \
  -H 'Content-Type: application/json' \
  -d '{"service":"RenderingControl","action":"SetVolume","args":{"InstanceID":0,"Channel":"Master","DesiredVolume":20},"confirm":true}'
```

## 開発ツール

ruff（lint + formatter）、ty（型チェック）、pre-commit を使用します。

```bash
make format   # ruff format .
make lint     # ty check . + ruff check .
make check    # ruff format --check + ruff check + ty check（CI 相当）

make precommit-install   # フックを git に登録
make precommit           # 全ファイルに対して実行
```

## テスト / 検証

```bash
make test                  # uv run coverage run -m pytest + report
```

`.claude/verify.sh` は Stop hook 用で、オフラインで `ruff format --check` +
`ruff check` + `ty check` + `pytest` を実行します（実機には触れません）。

## 注意

- ローカルネットワーク内（同一サブネット）からの利用を想定しています。認証は
  ありません。
- ファームウェアや機体によって UDN・ポート・公開サービスが異なる場合があります。
  DLNA のパスは device description から解決しているため多くは自動追従しますが、
  独自プロトコルのポート（TCP 30913 / UDP 16735）は `.env` で変更できます。
- AirPlay(7000/7100) や AndServer(7434) のエンドポイントは本 API の対象外です。

## 免責 / Disclaimer

本プロジェクトは **popIn Aladdin 非公式**であり、メーカーとは一切関係ありません。
標準 UPnP/DLNA の制御点を利用しています。

- **自分が管理権限を持つ機器に対してのみ**使用してください。
- ファームウェア更新で挙動が変わる可能性があります。
- 本ソフトウェアは現状有姿（AS IS）で提供され、いかなる保証もありません。

## ライセンス / License

[MIT](LICENSE)
