# CLAUDE.md

popIn Aladdin (天井照明付きプロジェクター) を同一 LAN から操作する REST サーバー (FastAPI + pydantic、Python 3.14、uv)。
UPnP/DLNA MediaRenderer (SOAP) と独自制御プロトコル (TCP / UDP) をラップする。
全体像・エンドポイント・プロトコルの詳細は README.md を参照する。

## セットアップと検証

- `mise trust` (新しい clone で 1 回) と `mise install`: ツールのインストールと git hooks (pre-commit / pre-push / commit-msg) の登録。`.venv` は最初の `uv run --locked` (`mise run test` 等) が `uv.lock` どおりに作る。`.pre-commit-config.yaml` を変えたら `mise exec -- prek install` で hook を登録し直す。
- `mise run lint`: ファイルを書き換えない検査 (ruff check / ruff format --check / lint-imports / ty check / pyright)。1 つが失敗しても全部を回してから失敗を返す。
- `mise run format`: リポジトリ全体の import の並べ替えと ruff format (ファイルを書き換える)。
- `mise run test`: coverage 付き pytest。テストは実機に触れず、`httpx.MockTransport` と localhost の TCP / UDP サーバーで検証する。
- `mise run pre-commit`: CI の `prek` job と同じ hook (dprint・actionlint・zizmor・hadolint・typos・ruff の整形・lint・gitleaks 等) を全追跡ファイルに実行する。整形の hook はファイルを書き換える。zizmor の online audit は token があるときだけ走る (README「開発」)。
- `mise run docs`: `mise.toml` の tasks を変更したあと README のタスク一覧を同期する。
- git hook: commit 時は整形の hook と lint、push 時は lint と test が走る (対象のファイルが変わったときだけ。README「pre-commit hooks」)。main を checkout しているときの commit は `no-commit-to-branch` hook が止める (`mise run pre-commit` はこの hook を除く)。commit 時の hook がファイルを書き換えると、その commit は失敗する。書き換えた差分を見直し、stage し直してから commit し直す。

## 規約

- commit message は Conventional Commits (`type(scope): subject`)。commit-msg hook の commitlint が検査する。
- python は ruff (format / lint)・ty・pyright・import-linter、json / yaml / markdown / toml / Dockerfile は dprint で検査・整形する。手で整えず、`mise run format` (python) と `mise run pre-commit` (全種類) に任せる。
- ruff・ty・pyright は strict に設定している (例: 2 引数目以降は keyword-only、相対 import と `from __future__ import annotations` の禁止、pyright は `strict`)。
- lint の指摘は原因を直し、設定 (規則・severity・hook の option) を緩めて通さない。誤検知と、外部の仕様 (呼び出し規約・プロトコル) のために直せない指摘だけを、理由のコメントを添えて最小の範囲で除外する。
  - python: 該当行に規則名付きの `# noqa: <code>`・`# ty: ignore[<rule>]`・`# pyright: ignore[<rule>]` (`# type: ignore` は ty・pyright とも無効。pyright は規則名の無い `# pyright: ignore` も受け付けるが、規則名を付ける)。
  - hadolint: `.hadolint.yaml` の `ignored` (Dockerfile 内の `# hadolint ignore=` は無効)。Dockerfile の `LABEL` を足すときは `.hadolint.yaml` の `label-schema` にも足す (schema に無い label は拒否される)。
  - typos: `typos.toml` の `extend-identifiers` / `extend-words`。
  - zizmor: 該当行の `# zizmor: ignore[<audit 名>]`。
- 層の依存は `pyproject.toml` の `[tool.importlinter]` が検査する。`popin_aladdin_api` の中は `main` → `api` → `settings` → `device` の向きにだけ依存し (途中の層は飛ばしてよい。`api` と `device` の中の層は契約の `layers` を見る。`|` で並べた同じ層のモジュールどうしは import できない)、fastapi は `main`・`api`、httpx は `device.renderer`、pydantic_settings は `settings` だけが直接 import できる。`popin_aladdin_api`・`api`・`device` の直下にモジュールを足したら、`exhaustive = true` の契約の `layers` にも足す (足さないと lint-imports が失敗する)。
- `.gitignore` はホワイトリスト方式。新しいファイルを追跡するときは対応する `!` の行を追記する。
- ツールは `mise.toml` に exact version で pin し、変更したら `mise lock` で `mise.lock` を追従させる。npm: backend のツール (pyright) は `mise.lock` が `.mise/locks/` の下の依存の lock を digest で参照するので、その差分も同じ commit に含め、手で編集しない。Python パッケージは `pyproject.toml` と `uv.lock` で固定し、`uv run --locked` で実行する。依存を変えたら `mise exec -- uv lock` で `uv.lock` を更新し、同じ commit に含める。`uv.lock` の取得元は `pyproject.toml` の `[[tool.uv.index]]` (`pypi.flatt.tech`) で、`UV_DEFAULT_INDEX`・`UV_INDEX` を設定した環境では変わりうるので、更新後に `uv.lock` の `registry` が変わっていないことを確かめる。Python 本体は `.python-version` (3.14) を uv が取得する。
- workflow の `uses:` は commit SHA で固定し、バージョンをコメントで併記する。
- コメント・ドキュメントは日本語で書き、技術用語・識別子は原語のまま使う。例外メッセージ・ログは英語。

## 設計上の制約

- デバイスに触るリクエストはプロセス内の 1 つの `asyncio.Lock` で直列化する (複数 SOAP 呼び出しから成る操作や D-pad の押下 → 離上列を崩さない)。uvicorn は単一プロセスで運用する。
- 認証は無く、LAN 内からの利用を前提にする。
- `device/` は FastAPI 非依存のまま保つ (import-linter の契約が検査する)。device 層の例外から HTTP status への変換は `main.py` の exception handler で行う。
- 設定は `settings.py` (pydantic-settings) で環境変数から読み、`.env` は読まない。必須は `POPIN_ALADDIN_HOST` (接続先のデバイス) だけで、`mise run` のタスクには `mise.toml` の `[env]` が渡す。
  mise の `[env]` はシェルの同名の変数より優先されるので、接続先を変えるときは git 管理外の `mise.local.toml` の `[env]` に書く。
