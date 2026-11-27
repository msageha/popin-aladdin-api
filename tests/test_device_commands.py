"""
UDP の JSON コマンド: POST /api/memory/free・capture・power/off と GET /api/remote/device。
"""

from typing import Any

import pytest
from hypothesis import example, given

from tests.harness import (
    DEVICE_INFO,
    FREE_MEMORY,
    POWER_OFF,
    SCREENSHOT,
    JsonValue,
    Stack,
)
from tests.strategies import as_json, non_boolean_json


def _command(mode_type: tuple[int, int]) -> dict[str, JsonValue]:
    """docs/protocol.md「独自プロトコル」の UDP JSON コマンド。"""
    mode, command_type = mode_type
    return {
        "action": 20000,
        "msgid": "2",
        "controlCmd": {"mode": mode, "type": command_type, "time": 0, "delayTime": 0},
    }


def test_free_memory_sends_command_without_waiting_for_reply(stack: Stack) -> None:
    stack.device.reset()

    response = stack.api.post("/api/memory/free")

    assert response.status_code == 200
    assert response.json() == {"action": "free_memory"}
    # JSON の型も比べる (Python の == は False と 0 を等しいとみなす)。
    assert as_json(stack.device.received_commands()) == as_json([_command(FREE_MEMORY)])


def test_capture_returns_image_url_on_the_device_host(stack: Stack) -> None:
    stack.device.reset()
    stack.device.command_replies[SCREENSHOT] = [
        {"action": 30235, "imagePath": "http://%s:7434/screenshot/1.png"}
    ]

    response = stack.api.post("/api/capture")

    assert response.status_code == 200
    # docs/protocol.md: imagePath の %s はデバイスの IP を入れる位置。
    assert response.json() == {
        "action": "capture",
        "image_url": "http://127.0.0.1:7434/screenshot/1.png",
    }
    assert as_json(stack.device.received_commands()) == as_json([_command(SCREENSHOT)])


def test_capture_ignores_other_replies_until_the_screenshot_reply(
    stack: Stack,
) -> None:
    stack.device.reset()
    stack.device.command_replies[SCREENSHOT] = [
        b"not json",
        b"[30235]",
        {"action": 30410, "deviceName": "Aladdin 2"},
        {"imagePath": "http://%s/no-action.png"},
        {"action": 30235, "imagePath": "http://%s:7434/screenshot.png"},
    ]

    response = stack.api.post("/api/capture")

    assert response.status_code == 200
    assert response.json()["image_url"] == "http://127.0.0.1:7434/screenshot.png"


def test_capture_without_reply_is_504(stack: Stack) -> None:
    stack.device.reset()
    stack.device.command_replies[SCREENSHOT] = []

    response = stack.api.post("/api/capture")

    assert response.status_code == 504


@pytest.mark.parametrize(
    "reply",
    [
        {"action": 30235},
        {"action": 30235, "imagePath": ""},
        {"action": 30235, "imagePath": 1},
        {"action": 30235, "imagePath": "http://%s/\ud800.png"},
    ],
    ids=[
        "no-image-path",
        "empty-image-path",
        "image-path-not-string",
        "lone-surrogate",
    ],
)
def test_screenshot_reply_without_image_path_is_502(
    *, stack: Stack, reply: dict[str, Any]
) -> None:
    stack.device.reset()
    stack.device.command_replies[SCREENSHOT] = [reply]

    response = stack.api.post("/api/capture")

    assert response.status_code == 502


def test_device_reports_runtime_information(stack: Stack) -> None:
    stack.device.reset()
    reply: dict[str, JsonValue] = {
        "action": 30410,
        "deviceName": "Aladdin 2",
        "deviceMode": "normal",
        "deviceApp": "TVer",
        "packageApp": "jp.co.tver.tvapp",
        "runtime": 3600,
        "deviceRom": 32,
        "mst": "0",
        "tips": "",
        "extra": [1],
    }
    stack.device.command_replies[DEVICE_INFO] = [reply]

    response = stack.api.get("/api/remote/device")

    assert response.status_code == 200
    assert response.json() == {
        "device_name": reply["deviceName"],
        "device_mode": reply["deviceMode"],
        "foreground_app": reply["deviceApp"],
        "foreground_package": reply["packageApp"],
        "runtime": reply["runtime"],
        "rom": reply["deviceRom"],
        "mst": reply["mst"],
        "tips": reply["tips"],
    }
    assert as_json(stack.device.received_commands()) == as_json([_command(DEVICE_INFO)])


def test_device_without_reply_is_504(stack: Stack) -> None:
    stack.device.reset()
    stack.device.command_replies[DEVICE_INFO] = []

    response = stack.api.get("/api/remote/device")

    assert response.status_code == 504


def test_device_reply_with_unexpected_value_is_502(stack: Stack) -> None:
    stack.device.reset()
    stack.device.command_replies[DEVICE_INFO] = [{"action": 30410, "runtime": "long"}]

    response = stack.api.get("/api/remote/device")

    assert response.status_code == 502


def test_power_off_with_confirm_sends_power_off(stack: Stack) -> None:
    stack.device.reset()

    response = stack.api.post("/api/power/off", json={"confirm": True})

    assert response.status_code == 200
    assert response.json() == {"action": "power_off"}
    assert as_json(stack.device.received_commands()) == as_json([_command(POWER_OFF)])


@pytest.mark.parametrize("body", [{}, {"confirm": False}])
def test_power_off_without_confirm_is_400_and_not_sent(
    *, stack: Stack, body: dict[str, Any]
) -> None:
    stack.device.reset()

    response = stack.api.post("/api/power/off", json=body)

    assert response.status_code == 400
    assert stack.device.received_commands() == []


@given(confirm=non_boolean_json)
@example(confirm="yes")
@example(confirm="true")
@example(confirm=1)
def test_power_off_with_non_boolean_confirm_is_422_and_not_sent(
    *, stack: Stack, confirm: object
) -> None:
    stack.device.reset()

    response = stack.api.post("/api/power/off", json={"confirm": confirm})

    assert response.status_code == 422
    assert stack.device.received_commands() == []
