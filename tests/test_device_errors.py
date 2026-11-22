"""デバイスの失敗と HTTP status の対応 (README「エラー」) と、device description の解決。"""

import socket
from pathlib import Path

import httpx
import pytest

from tests.harness import (
    API_TIMEOUT,
    FakeAladdin,
    HttpReply,
    Stack,
    run_api,
    serve_stack,
    soap_fault,
)

# 状態を読む操作と変える操作の両方で確かめる。
_ENDPOINTS = [
    ("GET", "/api/transport", "GetTransportInfo"),
    ("POST", "/api/pause", "Pause"),
]


def _call(stack: Stack, *, method: str, path: str) -> httpx.Response:
    return stack.api.get(path) if method == "GET" else stack.api.post(path)


@pytest.mark.parametrize(("method", "path", "action"), _ENDPOINTS)
def test_soap_fault_is_502_with_fault_and_upnp_error_codes(
    *, stack: Stack, method: str, path: str, action: str
) -> None:
    stack.reset()
    stack.device.soap_replies[action] = soap_fault(
        error_code="701", description="Transition not available"
    )

    response = _call(stack, method=method, path=path)

    assert response.status_code == 502
    body = response.json()
    assert body["fault_code"] == "s:Client"
    assert body["upnp_error_code"] == 701


def test_soap_fault_without_numeric_error_code_has_null_upnp_error_code(
    stack: Stack,
) -> None:
    stack.reset()
    stack.device.soap_replies["GetTransportInfo"] = soap_fault(
        error_code="unknown", description="broken"
    )

    response = stack.api.get("/api/transport")

    assert response.status_code == 502
    assert response.json()["upnp_error_code"] is None


@pytest.mark.parametrize(("method", "path", "action"), _ENDPOINTS)
@pytest.mark.parametrize(
    "reply",
    [
        HttpReply(500, b"<html>Internal Server Error</html>", "text/html"),
        HttpReply(200, b"<s:Envelope", 'text/xml; charset="utf-8"'),
        HttpReply(200, b"<root/>", 'text/xml; charset="utf-8"'),
    ],
    ids=["http-error-html", "truncated-xml", "not-soap-envelope"],
)
def test_reply_that_is_not_soap_is_502(
    *, stack: Stack, method: str, path: str, action: str, reply: HttpReply
) -> None:
    stack.reset()
    stack.device.soap_replies[action] = reply

    assert _call(stack, method=method, path=path).status_code == 502


@pytest.mark.parametrize(("method", "path"), [(m, p) for m, p, _ in _ENDPOINTS])
def test_dropped_connection_is_504(*, stack: Stack, method: str, path: str) -> None:
    stack.reset()
    stack.device.reachable = False

    assert _call(stack, method=method, path=path).status_code == 504


def test_reply_slower_than_timeout_is_504(stack: Stack) -> None:
    stack.reset()
    stack.device.soap_delays["GetTransportInfo"] = API_TIMEOUT + 1

    response = stack.api.get("/api/transport")

    assert response.status_code == 504


def test_device_refusing_connections_is_504_on_upnp_and_control_port(
    *, stack: Stack, tmp_path: Path
) -> None:
    # 待ち受けの無いポートへの接続は拒否される。bind して listen しないソケットへの接続は、macOS では
    # 拒否されずにタイムアウトになるので、API サーバーが起動する間だけ bind して (起動する API サーバー
    # 自身がそのポートを取らないように) から閉じる。
    with (
        socket.socket(socket.AF_INET, socket.SOCK_STREAM) as upnp,
        socket.socket(socket.AF_INET, socket.SOCK_STREAM) as control,
    ):
        upnp.bind(("127.0.0.1", 0))
        control.bind(("127.0.0.1", 0))
        settings = stack.device.api_env() | {
            "UPNP_PORT": str(upnp.getsockname()[1]),
            "CONTROL_TCP_PORT": str(control.getsockname()[1]),
        }
        with run_api(settings, log_path=tmp_path / "uvicorn.log") as api:
            upnp.close()
            control.close()

            assert api.get("/api/transport").status_code == 504
            assert api.post("/api/light", json={"button": "on"}).status_code == 504
            assert api.post("/api/remote/ping").status_code == 504


def test_device_is_reached_directly_even_with_proxy_settings(tmp_path: Path) -> None:
    # 実行環境に proxy の設定があっても、同じ LAN のデバイスへ直接つなぐ。proxy には、待ち受けない
    # ソケットのポートを指定する。テストの間は bind したままにし、fake や API サーバーがそのポートで
    # 待ち受けて proxy 宛ての要求に応答しないようにする。
    with (
        socket.socket(socket.AF_INET, socket.SOCK_STREAM) as proxy,
        FakeAladdin.serve() as device,
    ):
        proxy.bind(("127.0.0.1", 0))
        proxy_url = f"http://127.0.0.1:{proxy.getsockname()[1]}"
        settings = device.api_env() | dict.fromkeys(
            ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"), proxy_url
        )
        with run_api(settings, log_path=tmp_path / "uvicorn.log") as api:
            response = api.get("/api/transport")

    assert response.status_code == 200
    assert device.actions == ["GetTransportInfo"]


def test_description_at_configured_path_resolves_relative_control_urls(
    tmp_path: Path,
) -> None:
    with serve_stack(
        tmp_path / "uvicorn.log",
        description_path="/upnp/description.xml",
        relative_control_urls=True,
    ) as stack:
        info = stack.api.get("/api/info")
        transport = stack.api.get("/api/transport")
        volume = stack.api.get("/api/volume")

    assert info.status_code == 200
    port = stack.device.upnp_port
    assert info.json()["description_url"] == (
        f"http://127.0.0.1:{port}/upnp/description.xml"
    )
    assert transport.status_code == 200
    assert volume.status_code == 200
    assert stack.device.actions == ["GetTransportInfo", "GetVolume"]


def test_operation_on_service_the_device_lacks_is_502(tmp_path: Path) -> None:
    with serve_stack(
        tmp_path / "uvicorn.log", services=["AVTransport", "ConnectionManager"]
    ) as stack:
        volume = stack.api.get("/api/volume")
        transport = stack.api.get("/api/transport")
        info = stack.api.get("/api/info")

    assert volume.status_code == 502
    assert transport.status_code == 200
    assert sorted(info.json()["services"]) == ["AVTransport", "ConnectionManager"]


@pytest.mark.parametrize(
    "reply",
    [
        HttpReply(404, b"", "text/html"),
        HttpReply(200, b"<root", "text/xml"),
        HttpReply(200, b'<root xmlns="urn:schemas-upnp-org:device-1-0"/>', "text/xml"),
    ],
    ids=["http-error", "malformed-xml", "no-device-element"],
)
def test_unreadable_device_description_is_502(
    *, tmp_path: Path, reply: HttpReply
) -> None:
    with FakeAladdin.serve() as device:
        device.description_reply = reply
        with run_api(device.api_env(), log_path=tmp_path / "uvicorn.log") as api:
            info = api.get("/api/info")
            transport = api.get("/api/transport")

    assert info.status_code == 502
    assert transport.status_code == 502
    assert device.soap_calls == []
