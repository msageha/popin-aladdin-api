from collections.abc import Iterator

import pytest
from hypothesis import settings

from tests.harness import Stack, serve_stack

# 1 つの入力が 2 つのプロセスを跨ぐ HTTP の往復で、並列実行の負荷による遅れを入力ごとの失敗にしないため deadline を外す。
settings.register_profile("e2e", deadline=None)
settings.load_profile("e2e")


@pytest.fixture(scope="session")
def stack(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Stack]:
    """
    fake のデバイスと、それに接続した API サーバー (xdist の worker ごとに 1 組)。

    状態を共有するので、各テストと property の各入力は最初に `reset` を呼ぶ。API サーバーは
    device description を一度取得するとプロセスの終了まで使い続けるので、description を
    変えるテストは `serve_stack` で専用の組を起動する。
    """
    with serve_stack(tmp_path_factory.mktemp("api") / "uvicorn.log") as stack:
        yield stack
