"""リモコンキーの入力: POST /api/key と、ボタン名の一覧 GET /api/remote/buttons。"""

import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from tests.harness import Stack, serve_stack

# docs/protocol.md「独自プロトコル」の UDP キー入力の code。
_DPAD_CODES = {"home": 35, "up": 36, "right": 37, "down": 38, "ok": 49, "left": 50}
_FOCUS_CODES = {"focus_plus": 253, "focus_minus": 254}
_HARDWARE_CODES = {
    "back": 48,
    "vol_down": 114,
    "vol_up": 115,
    "power": 116,
    "menu": 139,
    "menu_long": 251,
    "settings": 300,
    "netflix": 301,
    "youtube": 302,
    "prime_video": 303,
    "custom": 304,
    "custom_long": 305,
}
_LIGHT_BUTTONS = [
    "switch",
    "brighter",
    "darker",
    "cooler",
    "warmer",
    "full",
    "night",
    "on",
    "off",
    "eco",
    "sleep",
]


def _press(code: int) -> str:
    return f"KEYSSTATUS:{code}+1"


def _release(code: int) -> str:
    return f"KEYSSTATUS:{code}+0"


def _assert_dpad_press(datagrams: list[str], *, code: int) -> None:
    """押下 → 全方向キーの離上 (順不同) → 押したキーの離上、の 1 回分であること。"""
    assert datagrams[0] == _press(code)
    assert Counter(datagrams[1:-1]) == Counter(
        _release(other) for other in _DPAD_CODES.values()
    )
    assert datagrams[-1] == _release(code)


@pytest.mark.parametrize("button", list(_DPAD_CODES))
def test_dpad_key_is_pressed_then_released(*, stack: Stack, button: str) -> None:
    stack.device.reset()

    response = stack.api.post("/api/key", json={"button": button})

    assert response.status_code == 200
    assert response.json() == {"button": button, "repeat": 1}
    datagrams = stack.device.received_keys()
    assert len(datagrams) == len(_DPAD_CODES) + 2
    _assert_dpad_press(datagrams, code=_DPAD_CODES[button])


@pytest.mark.parametrize("button", list(_FOCUS_CODES))
def test_focus_key_sends_press_and_release(*, stack: Stack, button: str) -> None:
    stack.device.reset()

    response = stack.api.post("/api/key", json={"button": button})

    assert response.status_code == 200
    code = _FOCUS_CODES[button]
    assert stack.device.received_keys() == [_press(code), _release(code)]


def test_home_long_holds_home_for_a_second(stack: Stack) -> None:
    stack.device.reset()
    started = time.monotonic()

    response = stack.api.post("/api/key", json={"button": "home_long"})

    assert response.status_code == 200
    home = _DPAD_CODES["home"]
    timed = stack.device.received_timed_keys()
    assert [key for _, key in timed] == [_press(home)] * 30 + [_release(home)]
    # docs/protocol.md: 押下を 30 回送り、1 秒後に離上する。fake の記録は届いた時刻より遅れうり、押下と離上の
    # 記録の間隔は負荷で縮みうるので、遅れても短くならない「要求を送り始めてから離上の記録まで」で
    # 1 秒を確かめる。
    assert timed[-1][0] - started >= 1.0


@pytest.mark.parametrize("button", list(_HARDWARE_CODES))
def test_hardware_key_sends_single_key_press(*, stack: Stack, button: str) -> None:
    stack.device.reset()

    response = stack.api.post("/api/key", json={"button": button})

    assert response.status_code == 200
    assert stack.device.received_keys() == [f"KEYPRESSES:{_HARDWARE_CODES[button]}"]


def test_repeat_presses_the_key_that_many_times(stack: Stack) -> None:
    stack.device.reset()

    response = stack.api.post("/api/key", json={"button": "down", "repeat": 3})

    assert response.status_code == 200
    assert response.json() == {"button": "down", "repeat": 3}
    per_press = len(_DPAD_CODES) + 2
    datagrams = stack.device.received_keys()
    assert len(datagrams) == per_press * 3
    for start in range(0, per_press * 3, per_press):
        _assert_dpad_press(
            datagrams[start : start + per_press], code=_DPAD_CODES["down"]
        )


@pytest.mark.parametrize("repeat", [1, 50])
def test_repeat_range_presses_single_key_that_many_times(
    *, stack: Stack, repeat: int
) -> None:
    stack.device.reset()

    response = stack.api.post("/api/key", json={"button": "vol_up", "repeat": repeat})

    assert response.status_code == 200
    assert response.json() == {"button": "vol_up", "repeat": repeat}
    assert (
        stack.device.received_keys()
        == [f"KEYPRESSES:{_HARDWARE_CODES['vol_up']}"] * repeat
    )


@pytest.mark.parametrize(
    "body",
    [
        {"button": "rewind"},
        {"button": "on"},
        {"button": "up", "repeat": 0},
        {"button": "up", "repeat": 51},
    ],
    ids=["unknown-key", "light-button", "repeat-0", "repeat-51"],
)
def test_invalid_request_is_422_and_not_sent(
    *, stack: Stack, body: dict[str, object]
) -> None:
    stack.device.reset()

    response = stack.api.post("/api/key", json=body)

    assert response.status_code == 422
    assert stack.device.received_keys() == []


def test_key_during_long_press_waits_until_release(stack: Stack) -> None:
    stack.device.reset()
    home, down = _DPAD_CODES["home"], _DPAD_CODES["down"]
    with ThreadPoolExecutor(max_workers=1) as executor:
        long_press = executor.submit(
            stack.api.post, "/api/key", json={"button": "home_long"}
        )
        # 長押しの押下が届いてから、離上までの 1 秒の間に別のキーを送る。
        stack.device.wait_for_keys(count=1)

        press = stack.api.post("/api/key", json={"button": "down"})

        assert long_press.result().status_code == 200
    assert press.status_code == 200
    per_press = len(_DPAD_CODES) + 2
    datagrams = stack.device.received_keys()
    assert datagrams[:31] == [_press(home)] * 30 + [_release(home)]
    assert len(datagrams) == 31 + per_press
    _assert_dpad_press(datagrams[31:], code=down)


def test_buttons_lists_every_light_button_and_key(tmp_path: Path) -> None:
    # device description を取得済みの API サーバーでは、取得しないことを確かめられない。
    with serve_stack(tmp_path / "uvicorn.log") as stack:
        response = stack.api.get("/api/remote/buttons")
        frames = stack.device.received_frames()

    assert response.status_code == 200
    buttons = response.json()
    assert sorted(buttons) == ["key", "key_stateless", "light"]
    assert sorted(buttons["light"]) == sorted(_LIGHT_BUTTONS)
    assert sorted(buttons["key"]) == sorted([*_DPAD_CODES, *_FOCUS_CODES, "home_long"])
    assert sorted(buttons["key_stateless"]) == sorted(_HARDWARE_CODES)
    assert stack.device.description_requests == 0
    assert stack.device.soap_calls == []
    assert frames == []
