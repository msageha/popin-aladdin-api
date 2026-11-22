"""シーリングライトの操作: POST /api/light。"""

import pytest

from tests.harness import REMOTE_CONTROL, Frame, Stack

# README「独自プロトコル」の RemoteControl の action。
_LIGHT_CODES = {
    "switch": 31,
    "brighter": 32,
    "darker": 33,
    "cooler": 34,
    "warmer": 35,
    "full": 36,
    "night": 37,
    "on": 38,
    "off": 39,
    "eco": 40,
    "sleep": 41,
}


def _light_frame(button: str) -> Frame:
    return Frame(*REMOTE_CONTROL, {"action": _LIGHT_CODES[button]})


@pytest.mark.parametrize("button", list(_LIGHT_CODES))
def test_button_sends_its_remote_control_action(*, stack: Stack, button: str) -> None:
    stack.reset()

    response = stack.api.post("/api/light", json={"button": button})

    assert response.status_code == 200
    assert response.json() == {"button": button, "repeat": 1}
    assert stack.device.received_frames() == [_light_frame(button)]


@pytest.mark.parametrize("repeat", [1, 3, 50])
def test_repeat_presses_the_button_that_many_times(
    *, stack: Stack, repeat: int
) -> None:
    stack.reset()

    response = stack.api.post(
        "/api/light", json={"button": "brighter", "repeat": repeat}
    )

    assert response.status_code == 200
    assert response.json() == {"button": "brighter", "repeat": repeat}
    assert stack.device.received_frames() == [_light_frame("brighter")] * repeat


@pytest.mark.parametrize(
    "body",
    [
        {"button": "strobe"},
        {"button": "ON"},
        {"button": "on", "repeat": 0},
        {"button": "on", "repeat": 51},
        {"repeat": 1},
    ],
    ids=["unknown-button", "uppercase", "repeat-0", "repeat-51", "no-button"],
)
def test_invalid_request_is_422_and_not_sent(
    *, stack: Stack, body: dict[str, object]
) -> None:
    stack.reset()

    response = stack.api.post("/api/light", json=body)

    assert response.status_code == 422
    assert stack.device.received_frames() == []
