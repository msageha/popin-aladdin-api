# popIn Aladdin API

[![CI](https://github.com/msageha/popin-aladdin-api/actions/workflows/ci.yaml/badge.svg?event=pull_request)](https://github.com/msageha/popin-aladdin-api/actions/workflows/ci.yaml)

天井照明付きプロジェクター popIn Aladdin を、同じ LAN から HTTP で操作する非公式の REST サーバーです。
クラウドを介さず、デバイスに直接つなぎます。

```mermaid
flowchart LR
    client([HTTP client]) -- "HTTP (REST)" --> api[popin-aladdin-api]
    api -- "UPnP/DLNA (SOAP)<br/>独自の TCP / UDP" --> dev[(popIn Aladdin)]
```

できること:

- 再生の操作・音量・ミュート、任意のメディア URL の再生 (キャスト)
- シーリングライトの点灯・消灯・明るさ・色温度
- リモコンのキー入力、文字入力、音声コマンド、アプリの起動
- デバイス情報の取得、スクリーンショット、電源断、LAN 内のデバイスの発見

> [!WARNING]
> 認証はありません。LAN 内の誰でも操作できる前提で運用してください。

## セットアップ

[mise](https://mise.jdx.dev/) を使います。

1. clone したリポジトリのルートでツールを入れます。Python と依存は、最初の `mise run dev` で uv が用意します。

   ```bash
   mise trust
   mise install
   ```

2. 接続先のデバイスの IP アドレスかホスト名を、git 管理外の `mise.local.toml` に書きます。
   `mise.toml` には作者の環境の接続先があり、シェルの環境変数より優先されるので、シェルではなくこのファイルで上書きします。

   ```toml
   [env]
   POPIN_ALADDIN_HOST = "192.168.1.20"
   ```

## 起動

```bash
mise run dev
```

| URL                                | 内容                                                    |
| ---------------------------------- | ------------------------------------------------------- |
| `http://127.0.0.1:8000/api/health` | 応答の `host` で接続先を確かめる (デバイスには触れない) |
| `http://127.0.0.1:8000/docs`       | Swagger UI。リクエストとレスポンスの形を確かめ、試せる  |

### 設定

設定は環境変数で渡します。必須は `POPIN_ALADDIN_HOST` だけで、ほかは機種やファームウェアで既定値と違うときだけ変えます。

| 変数                     | 既定値  | 説明                                                        |
| ------------------------ | ------- | ----------------------------------------------------------- |
| `POPIN_ALADDIN_HOST`     | (必須)  | デバイスの URL またはホスト名 / IP (ポートは含めない)       |
| `UPNP_PORT`              | `1481`  | UPnP/DLNA MediaRenderer のポート                            |
| `DESCRIPTION_PATH`       | `/`     | UPnP device description のパス                              |
| `CONTROL_TCP_PORT`       | `30913` | 制御用 TCP (ライト・文字入力・音声・アプリ起動・情報の照会) |
| `CONTROL_UDP_PORT`       | `16735` | キー入力の UDP                                              |
| `CONTROL_CMD_UDP_PORT`   | `16750` | コマンドの UDP (スクリーンショット・メモリ解放・電源断 等)  |
| `CONTROL_REPLY_UDP_PORT` | `16751` | コマンドの応答をこのサーバーが受け取る UDP ポート           |
| `DISCOVERY_UDP_PORT`     | `8100`  | デバイスの発見でブロードキャストを送るポート                |
| `TIMEOUT`                | `10`    | デバイスへの各リクエストのタイムアウト (秒)                 |

デバイスへは proxy の設定 (`HTTP_PROXY` 等) を使わずに直接つなぎます。

### Docker

```bash
mise run run-image
```

Docker で動かすときの注意です。`mise run run-image` は表の 1・2 行目を設定済みです。

| 項目                                                           | 理由・方法                                                                                                                                                                                                                |
| -------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `POPIN_ALADDIN_HOST` を環境変数で渡す                          | イメージに接続先は含まれない                                                                                                                                                                                              |
| bridge ネットワークでは `CONTROL_REPLY_UDP_PORT` を UDP で公開 | `/api/capture` と `/api/remote/device` の応答はデバイスから UDP で届く (例: `-p 16751:16751/udp`)                                                                                                                         |
| healthcheck は exec 形式で書く                                 | イメージは shell の無い distroless (下の例)                                                                                                                                                                               |
| `/api/discover` を使うなら `--network host`                    | ブロードキャストは Docker の既定の bridge ネットワークから LAN に届かない (`--network host` は Linux の Docker Engine で使える)。ホストで直接起動してもよい。host ネットワークではポートの公開 (`-p`・`ports`) は要らない |

```yaml
healthcheck:
  test: [
    "CMD",
    "python",
    "-c",
    "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')",
  ]
```

## API

パスはすべて `/api` から始まります。

| 用途             | エンドポイント                                                                                                  |
| ---------------- | --------------------------------------------------------------------------------------------------------------- |
| サーバーの状態   | `GET /health` (デバイスには触れない)                                                                            |
| 再生状態の取得   | `GET /status` (まとめて取得) `/info` `/transport` `/position` `/media` `/protocol-info`                         |
| 再生の操作       | `POST /play` `/pause` `/stop` `/next` `/previous` `/seek` `/play-mode` `/cast`                                  |
| 音量・ミュート   | `GET` / `POST /volume` `/mute`                                                                                  |
| ライト           | `POST /light`                                                                                                   |
| キー・文字入力   | `POST /key` `/keyboard` `/voice`、`GET /remote/buttons` (使えるボタン名の一覧)                                  |
| アプリの起動     | `POST /deeplink`                                                                                                |
| デバイスの情報   | `GET /remote/version` `/remote/album` `/remote/apps/{package}` `/remote/device`、`POST /remote/ping` (疎通確認) |
| デバイスの操作   | `POST /capture` (スクリーンショット) `/memory/free` `/power/off`                                                |
| デバイスの発見   | `GET /discover`                                                                                                 |
| 任意の SOAP 呼出 | `POST /soap`                                                                                                    |

`/api/cast` の URL はデバイスから取得できる必要があります。`/api/capture` が返す `image_url` も、デバイスと同じ LAN から取得します。
`/api/power/off` と `/api/soap` には、誤操作を防ぐため `"confirm": true` が要ります。`/api/soap` で省けるのは、`GetVolume`・`GetTransportInfo` など、この API が読み取り専用として登録したアクションだけです。
電源を切ると、この API からは再び電源を入れられません。

### 使用例

```bash
# 再生状態をまとめて取得する
curl http://127.0.0.1:8000/api/status

# 音量を 40 にする
curl -X POST http://127.0.0.1:8000/api/volume -H 'Content-Type: application/json' -d '{"volume": 40}'

# LAN 上の動画を再生する
curl -X POST http://127.0.0.1:8000/api/cast -H 'Content-Type: application/json' \
  -d '{"uri": "http://192.168.1.50:8200/video/sample.mp4", "upnp_class": "object.item.videoItem"}'

# ライトを点けて、明るさを 10 段階上げる
curl -X POST http://127.0.0.1:8000/api/light -H 'Content-Type: application/json' -d '{"button": "on"}'
curl -X POST http://127.0.0.1:8000/api/light -H 'Content-Type: application/json' -d '{"button": "brighter", "repeat": 10}'

# リモコンでカーソルを下へ動かして決定する
curl -X POST http://127.0.0.1:8000/api/key -H 'Content-Type: application/json' -d '{"button": "down"}'
curl -X POST http://127.0.0.1:8000/api/key -H 'Content-Type: application/json' -d '{"button": "ok"}'

# YouTube を開く (実機では未確認の操作。docs/protocol.md「動作の確認状況」)
curl -X POST http://127.0.0.1:8000/api/deeplink -H 'Content-Type: application/json' -d '{"url": "https://www.youtube.com/tv"}'
```

### エラー

| Status | 意味                                                                                                                                             |
| ------ | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| 400    | `confirm: true` が要る操作に付いていない                                                                                                         |
| 422    | リクエストが不正 (未知のボタン名・範囲外の音量・boolean の項目に `true` / `false` 以外の値等)。`detail` には送った値を含めない                   |
| 502    | デバイスがエラーや想定外の応答を返した。SOAP fault なら body に `fault_code` (SOAP faultcode) と `upnp_error_code` (UPnPError errorCode) を含む  |
| 504    | デバイスに接続できない・通信が途中で切れた・タイムアウトした。`/api/capture`・`/api/remote/device` では、UDP の応答が `TIMEOUT` 秒以内に届かない |

## 制約

- 制御の多くは公式アプリの解析で復元した非公開のプロトコルによるもので、一部は実機で動作を確かめていません ([プロトコルの詳細](docs/protocol.md))。
  ファームウェアの更新で動かなくなることがあります。
- UDP で送るだけの操作 (`/api/key`・`/api/memory/free`・`/api/power/off`) は、デバイスが応答しなくても 200 を返します。
- デバイスへの操作は 1 つずつ順に実行します。この直列化はプロセスの中でだけ効くので、uvicorn は 1 プロセス (`--workers 1`) で動かしてください。
- デバイスの UPnP の情報は起動中キャッシュします。デバイスを入れ替えたらサーバーを再起動してください。

## 開発

| 文書                                       | 内容                                             |
| ------------------------------------------ | ------------------------------------------------ |
| [docs/development.md](docs/development.md) | コードの構成・テスト・検査・CI・リポジトリの設定 |
| [docs/protocol.md](docs/protocol.md)       | デバイスの各ポートのプロトコルと、動作の確認状況 |

## 免責 / Disclaimer

本プロジェクトは popIn Aladdin の**非公式**のソフトウェアで、メーカーとは関係ありません。
自分が管理する機器にだけ使ってください。本ソフトウェアは現状有姿 (AS IS) で提供され、いかなる保証もありません。

## ライセンス / License

[MIT](LICENSE)

## タスク

`mise run <task>` で実行します。

<!-- dprint-ignore-start -->
<!-- mise-tasks -->
## `build-image`

- **Usage:** `build-image`

Docker イメージ `popin-aladdin-api:latest` を build する

## `check-image`

- Depends: build-image

- **Usage:** `check-image`

Docker イメージを build し、起動して `/api/health` が応答するかを確かめる (CI の `image` job と同じ)。

デバイスには接続しない。root filesystem を read-only にし、capability をすべて外した状態で確かめる。

## `clean`

- **Usage:** `clean`

検査とテストが作るキャッシュを削除する

## `dev`

- **Usage:** `dev`

API サーバーを http://127.0.0.1:8000 で起動する (コードを変更すると自動で再起動する)

## `docs`

- **Usage:** `docs`

README.md のタスク一覧を、mise.toml のタスクの定義から生成し直す。

mise.toml か README.md を commit するときは、hook が自動で実行する。

## `format`

- **Usage:** `format`

Python のコードの import を並べ替え、整形する (ファイルを書き換える)

## `lint`

- **Usage:** `lint`

Python のコードを、ファイルを書き換えずに検査する (lint・整形・モジュール間の依存・型)。

1 つの検査が失敗しても残りを実行し、最後に失敗を返す。

## `pre-commit`

- **Usage:** `pre-commit`

commit 時の hook を、git で追跡している全ファイルに実行する。

整形の hook はファイルを書き換える。main への commit を止める hook は実行しない。

## `run-image`

- Depends: build-image

- **Usage:** `run-image`

Docker イメージ `popin-aladdin-api:latest` を build して起動する。

設定されている環境変数をコンテナに渡し、root filesystem を read-only にして capability をすべて外した状態で起動する。
API はホストのすべてのネットワークインターフェースの 8000/tcp に公開する。デバイスからの UDP の応答を受けるため、`CONTROL_REPLY_UDP_PORT` (既定 16751) も UDP で公開する。

## `test`

- **Usage:** `test`

テストを実行し、coverage を表示する。

テストは実機に接続せず、テスト用の偽のデバイスを相手に動く。
<!-- /mise-tasks -->
<!-- dprint-ignore-end -->
