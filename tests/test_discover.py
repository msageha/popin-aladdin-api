"""LAN 内のデバイスの発見: GET /api/discover。"""

from pathlib import Path
from typing import Any

import pytest

from tests.harness import FakeAladdin, JsonValue, Stack, discovery_reply, run_api

_WAIT = {"wait": 0.5}


def _device(ip: str, **fields: JsonValue) -> dict[str, JsonValue]:
    return {
        "ipAddress": ip,
        "model": "Aladdin 2",
        "name": f"Aladdin at {ip}",
        "pid": f"PID-{ip}",
        "mac": "54:F1:5F:16:4D:4F",
        "version": 1,
        "zipcode": "1000001",
        "isConnected": False,
    } | fields


def _discovered(device: dict[str, JsonValue]) -> dict[str, JsonValue]:
    return {
        "ip_address": device["ipAddress"],
        "model": device["model"],
        "name": device["name"],
        "pid": device["pid"],
        "mac": device["mac"],
        "version": device["version"],
        "zipcode": device["zipcode"],
        "connected": device["isConnected"],
    }


def _by_ip(devices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # 応答の順序は決まっていない。
    return sorted(devices, key=lambda d: d["ip_address"])


def test_discover_broadcasts_request_and_lists_replying_devices(stack: Stack) -> None:
    stack.device.reset()
    # 応答の種別ごとに、JSON の長さのフィールドの形が違う (17 は 1 byte、19 / 21 は 4 byte)。
    # 4 byte の長さは、上位の byte も読むことを確かめるため 255 byte より長い JSON にする。
    devices = {
        17: _device("192.0.2.10"),
        19: _device("192.0.2.11", isConnected=True, name="A" * 300),
        21: _device("192.0.2.12", name="B" * 300),
    }
    stack.device.discovery_replies = [
        discovery_reply(device, kind=kind) for kind, device in devices.items()
    ]

    response = stack.api.get("/api/discover", params=_WAIT)

    assert response.status_code == 200
    assert _by_ip(response.json()) == [_discovered(d) for d in devices.values()]
    [request] = stack.device.received_discovery_requests()
    assert request.data == (b"aladdin" + bytes([0x14])).ljust(1024, b"\0")
    assert request.destination == "255.255.255.255"


def test_discover_waits_for_replies_until_wait_seconds(stack: Stack) -> None:
    stack.device.reset()
    device = _device("192.0.2.10")
    stack.device.discovery_replies = [discovery_reply(device)]
    # 最短の待ち時間 (0.5 秒) より遅れて届く応答も、指定した待ち時間の内なら拾う。
    stack.device.discovery_reply_delay = 0.8

    response = stack.api.get("/api/discover", params={"wait": 1.2})

    assert response.status_code == 200
    assert response.json() == [_discovered(device)]


def test_discover_ignores_replies_after_wait_seconds(stack: Stack) -> None:
    stack.device.reset()
    stack.device.discovery_replies = [discovery_reply(_device("192.0.2.10"))]
    stack.device.discovery_reply_delay = 0.8

    response = stack.api.get("/api/discover", params={"wait": 0.5})

    assert response.status_code == 200
    assert response.json() == []
    # 遅れて送る応答が次のテストに届かないよう、fake が応答を送り終えるまで待つ。
    stack.device.received_discovery_requests()


def test_discover_accepts_devices_other_than_the_configured_host(
    tmp_path: Path,
) -> None:
    # 応答は 127.0.0.1 の fake から届く。接続先を別の address にした API サーバーでも拾う。
    device_reply = _device("127.0.0.1")
    with FakeAladdin() as device:
        device.discovery_replies = [discovery_reply(device_reply)]
        settings = device.api_env() | {"POPIN_ALADDIN_HOST": "http://192.0.2.1"}
        with run_api(settings, log_path=tmp_path / "uvicorn.log") as api:
            response = api.get("/api/discover", params=_WAIT)

    assert response.status_code == 200
    assert response.json() == [_discovered(device_reply)]


def test_discover_lists_each_device_once(stack: Stack) -> None:
    stack.device.reset()
    device = _device("192.0.2.10")
    stack.device.discovery_replies = [
        discovery_reply(device, kind=17),
        discovery_reply(device, kind=17),
    ]

    response = stack.api.get("/api/discover", params=_WAIT)

    assert response.status_code == 200
    assert response.json() == [_discovered(device)]


def test_discover_skips_replies_that_are_not_aladdin_devices(stack: Stack) -> None:
    stack.device.reset()
    valid = _device("192.0.2.10")
    stack.device.discovery_replies = [
        b"other device",
        b"aladdin",
        b"aladdin\x63\x02{}",
        b"aladdin\x11\x08not json",
        discovery_reply([1, 2]),
        discovery_reply(_device("192.0.2.20", version="new")),
        discovery_reply(_device("192.0.2.21", name="\ud800")),
        discovery_reply(valid),
    ]

    response = stack.api.get("/api/discover", params=_WAIT)

    assert response.status_code == 200
    assert response.json() == [_discovered(valid)]


def test_discover_without_replies_is_empty(stack: Stack) -> None:
    stack.device.reset()

    response = stack.api.get("/api/discover", params=_WAIT)

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.parametrize("wait", [0.49, 15.01, "soon"])
def test_wait_outside_half_to_15_seconds_is_422(
    *, stack: Stack, wait: float | str
) -> None:
    stack.device.reset()

    response = stack.api.get("/api/discover", params={"wait": wait})

    assert response.status_code == 422
    assert stack.device.received_discovery_requests() == []
