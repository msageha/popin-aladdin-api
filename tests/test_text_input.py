"""文字列を送る操作: POST /api/keyboard・voice・deeplink。"""

from typing import Any

import pytest
from hypothesis import example, given, strategies as st

from tests.harness import DEEPLINK, IME, VOICE, Frame, Stack
from tests.strategies import as_json

_TEXT_ENDPOINTS: dict[str, tuple[tuple[int, int], str]] = {
    "/api/keyboard": (IME, "text"),
    "/api/voice": (VOICE, "text"),
    "/api/deeplink": (DEEPLINK, "url"),
}


def _expected_frame(path: str, *, text: str) -> Frame:
    frame_type, _ = _TEXT_ENDPOINTS[path]
    payload: dict[str, Any] = {
        "/api/keyboard": {"text": text},
        "/api/voice": {"text": text, "success": True},
        "/api/deeplink": {"deepLink": text},
    }[path]
    return Frame(*frame_type, payload)


def _assert_frames(stack: Stack, *, expected: list[Frame]) -> None:
    # Frame の == は True と 1 を等しいとみなすので、JSON の型も比べる。
    frames = stack.device.received_frames()
    assert frames == expected
    assert as_json([f.payload for f in frames]) == as_json(
        [f.payload for f in expected]
    )


@given(path=st.sampled_from(list(_TEXT_ENDPOINTS)), text=st.text(min_size=1))
@example(path="/api/keyboard", text="hello world")
@example(path="/api/voice", text="電気をつけて")
@example(path="/api/deeplink", text="https://www.youtube.com/tv")
@example(path="/api/keyboard", text='"\\\n\x00')
@example(path="/api/keyboard", text="\U0001f600")
def test_text_reaches_device_unchanged(*, stack: Stack, path: str, text: str) -> None:
    stack.device.reset()
    _, field = _TEXT_ENDPOINTS[path]

    response = stack.api.post(path, json={field: text})

    assert response.status_code == 200
    assert response.json() == {field: text}
    _assert_frames(stack, expected=[_expected_frame(path, text=text)])


@pytest.mark.parametrize("path", ["/api/keyboard", "/api/voice"])
def test_empty_text_is_sent(*, stack: Stack, path: str) -> None:
    stack.device.reset()

    response = stack.api.post(path, json={"text": ""})

    assert response.status_code == 200
    _assert_frames(stack, expected=[_expected_frame(path, text="")])


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/api/deeplink", {"url": ""}),
        ("/api/deeplink", {}),
        ("/api/keyboard", {}),
        ("/api/voice", {"text": None}),
    ],
    ids=["empty-deeplink", "no-url", "no-text", "null-text"],
)
def test_invalid_request_is_422_and_not_sent(
    *, stack: Stack, path: str, body: dict[str, Any]
) -> None:
    stack.device.reset()

    response = stack.api.post(path, json=body)

    assert response.status_code == 422
    assert stack.device.received_frames() == []


# UTF-8 で表せない孤立した surrogate (JSON の文字列の escape では書ける)。
@pytest.mark.parametrize("path", list(_TEXT_ENDPOINTS))
@pytest.mark.parametrize(
    "escaped",
    ["\\ud800", "a\\udfffb", "\\ude00\\ud83d"],
    ids=["high", "low", "reversed-pair"],
)
def test_text_with_lone_surrogate_is_422_and_not_sent(
    *, stack: Stack, path: str, escaped: str
) -> None:
    stack.device.reset()
    _, field = _TEXT_ENDPOINTS[path]

    response = stack.api.post(
        path,
        content=f'{{"{field}": "{escaped}"}}'.encode(),
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422
    assert stack.device.received_frames() == []
