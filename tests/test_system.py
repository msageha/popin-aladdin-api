"""サーバーの起動と GET /api/health。"""

import subprocess
from pathlib import Path

import pytest

from tests.harness import API_COMMAND, API_HOST, run_api, serve_stack


def test_health_reports_configured_host_without_contacting_device(
    tmp_path: Path,
) -> None:
    # device description を取得済みの API サーバーでは、取得しないことを確かめられない。
    with serve_stack(tmp_path / "uvicorn.log") as stack:
        response = stack.api.get("/api/health")

        assert response.status_code == 200
        assert response.json() == {"status": "ok", "host": API_HOST}
        assert stack.device.description_requests == 0
        assert stack.device.soap_calls == []
        assert stack.device.received_frames() == []
        assert stack.device.received_keys() == []
        assert stack.device.received_commands() == []


def test_server_starts_with_only_device_host(tmp_path: Path) -> None:
    # 必須の設定は接続先だけ。下の起動の失敗が接続先の設定によることの対照にもなる。
    with run_api({"POPIN_ALADDIN_HOST": API_HOST}, log_path=tmp_path / "log") as api:
        response = api.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "host": API_HOST}


@pytest.mark.parametrize(
    "settings", [{}, {"POPIN_ALADDIN_HOST": ""}], ids=["unset", "empty"]
)
def test_server_refuses_to_start_without_device_host(settings: dict[str, str]) -> None:
    result = subprocess.run(  # noqa: S603 - 引数は固定値と sys.executable だけ
        API_COMMAND,
        cwd=Path(__file__).resolve().parents[1],
        # coverage の変数を渡さない。起動に失敗するプロセスも main.py を import するので、計測すると
        # 起動した API サーバーの計測が欠けても mise run test の検査が main.py を計測済みとみなす。
        env=settings,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert result.returncode != 0
    assert b"Uvicorn running" not in result.stderr
