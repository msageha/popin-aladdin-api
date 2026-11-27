"""シーリングライトの操作: POST /api/light。"""

import pytest
from hypothesis import example, given

from tests.harness import REMOTE_CONTROL, Frame, Stack
from tests.strategies import non_number_json

# docs/protocol.md「独自プロトコル」の RemoteControl の action。
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
    stack.device.reset()

    response = stack.api.post("/api/light", json={"button": button})

    assert response.status_code == 200
    assert response.json() == {"button": button, "repeat": 1}
    assert stack.device.received_frames() == [_light_frame(button)]


@pytest.mark.parametrize("repeat", [1, 3, 50])
def test_repeat_presses_the_button_that_many_times(
    *, stack: Stack, repeat: int
) -> None:
    stack.device.reset()

    response = stack.api.post(
        "/api/light", json={"button": "brighter", "repeat": repeat}
    )

    assert response.status_code == 200
    assert response.json() == {"button": "brighter", "repeat": repeat}
    assert stack.device.received_frames() == [_light_frame("brighter")] * repeat


# JSON Schema の integer は小数部が 0 の数 (3.0) も含む。
def test_repeat_with_zero_fraction_presses_the_button_that_many_times(
    stack: Stack,
) -> None:
    stack.device.reset()

    response = stack.api.post("/api/light", json={"button": "brighter", "repeat": 3.0})

    assert response.status_code == 200
    assert stack.device.received_frames() == [_light_frame("brighter")] * 3


@given(repeat=non_number_json)
@example(repeat=True)
@example(repeat="3")
def test_non_number_repeat_is_422_and_not_sent(*, stack: Stack, repeat: object) -> None:
    stack.device.reset()

    response = stack.api.post("/api/light", json={"button": "on", "repeat": repeat})

    assert response.status_code == 422
    assert stack.device.received_frames() == []


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
    stack.device.reset()

    response = stack.api.post("/api/light", json=body)

    assert response.status_code == 422
    assert stack.device.received_frames() == []
