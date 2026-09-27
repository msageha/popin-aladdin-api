# CLAUDE.md

popIn Aladdin (天井照明付きプロジェクター) を同一 LAN から操作する REST サーバー (FastAPI + pydantic、Python 3.14、uv)。
UPnP/DLNA MediaRenderer (SOAP) と独自制御プロトコル (TCP / UDP) をラップする。
全体像・エンドポイント・プロトコルの詳細は README.md を参照する。

## セットアップと検証

- `mise install`: ツールのインストールと git hooks (pre-commit / commit-msg) のセットアップ。`.venv` は最初の `uv run --locked` (`mise run test` 等) が `uv.lock` どおりに作る。
- `mise run lint`: ruff format --check + ruff check + ty check。
- `mise run test`: coverage 付き pytest。テストは実機に触れず、`httpx.MockTransport` と localhost の TCP / UDP サーバーで検証する。
- `mise exec -- prek run --all-files`: 全 hook (dprint、actionlint、hadolint、ruff、ty、gitleaks 等) を実行する。CI の `prek` job と同じ検証。
- `mise run docs`: `mise.toml` の tasks を変更したあと README のタスク一覧を同期する。

## 規約

- commit message は Conventional Commits (`type(scope): subject`)。commit-msg hook の commitlint が検査する。
- python は ruff (format / lint) と ty に、json / yaml / markdown / toml は dprint に整形を任せる。手で整えず `prek run --all-files` に任せる。
- `.gitignore` はホワイトリスト方式。新しいファイルを追跡するときは対応する `!` の行を追記する。
- ツールは `mise.toml` に exact version で pin し、変更したら `mise lock` で `mise.lock` を追従させる。Python パッケージは `pyproject.toml` と `uv.lock` で固定し、`uv run --locked` で実行する。Python 本体は `.python-version` (3.14) を uv が取得する。
- workflow の `uses:` は commit SHA で固定し、バージョンをコメントで併記する。
- コメント・ドキュメントは日本語で書き、技術用語・識別子は原語のまま使う。例外メッセージ・ログは英語。

## 設計上の制約

- デバイスに触るリクエストはプロセス内の 1 つの `asyncio.Lock` で直列化する (複数 SOAP 呼び出しから成る操作や D-pad の押下 → 離上列を崩さない)。uvicorn は単一プロセスで運用する。
- 認証は無く、LAN 内からの利用を前提にする。
- `device/` は FastAPI 非依存のまま保つ。device 層の例外から HTTP status への変換は `main.py` の exception handler で行う。
- 設定は `settings.py` (pydantic-settings) で環境変数 / `.env` から読む。全て省略可で `.env` は任意。
