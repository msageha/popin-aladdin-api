FROM ghcr.io/astral-sh/uv:0.13.9-trixie-slim@sha256:9b7790faef7a3f2b9ba8f2f7c48b959c1359fe2bd51c44804b6ca61766fbacdf AS builder

# distroless には Python 3.14 の image が無いので、uv が配布する Python を入れて runner へ同じパスで写す
# (venv の python は /python の下の実体を絶対パスの symlink で指す)。minor は .python-version、patch は uv の版で決まる。
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_INSTALL_DIR=/python \
    UV_PYTHON_PREFERENCE=only-managed

WORKDIR /app
COPY .python-version ./
# runner で使わない大きなもの (tcl/tk・pip・ヘッダ等と、python3.14 が static link しているので不要な libpython の
# 共有ライブラリ) を消す。インストール先は版と arch を名前に含むので glob で探す (cpython-3.14-linux-* は同じ実体への
# symlink)。削除はサイズのためだけなので、配布物から対象が無くなっても build を止めない (-f)。
RUN uv python install \
 && for p in /python/cpython-3.*.*-linux-*; do \
      test -d "$p" && rm -rf -- "$p"/include "$p"/share "$p"/lib/libpython*.so* "$p"/lib/*tcl* "$p"/lib/tk* \
        "$p"/lib/python3.*/site-packages/* "$p"/lib/python3.*/ensurepip "$p"/lib/python3.*/idlelib "$p"/lib/python3.*/tkinter; \
    done

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY README.md LICENSE ./
COPY src ./src
RUN uv sync --locked --no-dev --no-editable

# uv の Python は glibc と libgcc_s に動的リンクするので、それらを持つ cc を使う。
FROM gcr.io/distroless/cc-debian13:nonroot@sha256:cb87acc574abe719b6e5c547384defa2f7b1f24af9605d3f618cf852495d8be2 AS runner

LABEL org.opencontainers.image.source="https://github.com/msageha/popin-aladdin-api" \
      org.opencontainers.image.licenses="MIT"

WORKDIR /app
COPY --from=builder /python /python
COPY --from=builder /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1

# base の nonroot tag も UID 65532 だが、digest を取り違えても root で動かないよう明示する。
# 数値にすると実行環境側 (Kubernetes の runAsNonRoot 等) が非 root を検証できる。
USER 65532
EXPOSE 8000

# POPIN_ALADDIN_HOST (必須) はイメージに含めず、実行時に環境変数で渡す。
CMD ["uvicorn", "popin_aladdin_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
