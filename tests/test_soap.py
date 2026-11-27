"""任意の SOAP アクションのパススルー: POST /api/soap。"""

from typing import Any

import pytest
from hypothesis import example, given, strategies as st

from tests.harness import Stack
from tests.strategies import non_boolean_json, xml_text


@pytest.mark.parametrize(
    ("service", "action", "args"),
    [
        ("AVTransport", "GetTransportInfo", {"InstanceID": 0}),
        ("RenderingControl", "GetVolume", {"InstanceID": 0, "Channel": "Master"}),
        ("ConnectionManager", "GetProtocolInfo", {}),
    ],
)
def test_read_action_is_sent_without_confirm_and_returns_outputs(
    *, stack: Stack, service: str, action: str, args: dict[str, Any]
) -> None:
    stack.device.reset()

    response = stack.api.post(
        "/api/soap", json={"service": service, "action": action, "args": args}
    )

    assert response.status_code == 200
    assert response.json() == {
        "service": service,
        "action": action,
        "result": stack.device.soap_outputs[action],
    }
    [call] = stack.device.soap_calls
    assert (call.service, call.action) == (service, action)
    assert call.args == {name: str(value) for name, value in args.items()}


@pytest.mark.parametrize("confirm", [None, False])
@pytest.mark.parametrize(
    ("service", "action"),
    [("RenderingControl", "SetVolume"), ("AVTransport", "GetVendorState")],
    ids=["control", "unknown-get"],
)
def test_action_not_known_as_read_only_without_confirm_is_400_and_not_sent(
    *, stack: Stack, service: str, action: str, confirm: bool | None
) -> None:
    stack.device.reset()
    body: dict[str, Any] = {
        "service": service,
        "action": action,
        "args": {"InstanceID": 0},
    }
    if confirm is not None:
        body["confirm"] = confirm

    response = stack.api.post("/api/soap", json=body)

    assert response.status_code == 400
    assert stack.device.soap_calls == []


def test_control_action_with_confirm_is_sent(stack: Stack) -> None:
    stack.device.reset()

    response = stack.api.post(
        "/api/soap",
        json={
            "service": "RenderingControl",
            "action": "SetVolume",
            "args": {"InstanceID": 0, "Channel": "Master", "DesiredVolume": 20},
            "confirm": True,
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "service": "RenderingControl",
        "action": "SetVolume",
        "result": {},
    }
    [call] = stack.device.soap_calls
    assert (call.service, call.action) == ("RenderingControl", "SetVolume")
    assert call.args == {"InstanceID": "0", "Channel": "Master", "DesiredVolume": "20"}


@given(confirm=non_boolean_json)
@example(confirm="yes")
@example(confirm="true")
@example(confirm=1)
def test_control_action_with_non_boolean_confirm_is_422_and_not_sent(
    *, stack: Stack, confirm: object
) -> None:
    stack.device.reset()

    response = stack.api.post(
        "/api/soap",
        json={
            "service": "RenderingControl",
            "action": "SetVolume",
            "args": {"InstanceID": 0, "Channel": "Master", "DesiredVolume": 20},
            "confirm": confirm,
        },
    )

    assert response.status_code == 422
    assert stack.device.soap_calls == []


@given(
    args=st.dictionaries(
        st.from_regex(r"[A-Za-z_][A-Za-z0-9_.-]{0,15}", fullmatch=True),
        xml_text,
        max_size=4,
    )
)
@example(args={"CurrentURI": "http://h/a?b=1&c=<d>", "Quote": "\"'"})
@example(args={"Lines": "a\r\nb\rc\n", "Blank": "", "Spaces": "  x  "})
def test_string_arguments_reach_device_unchanged(
    *, stack: Stack, args: dict[str, str]
) -> None:
    stack.device.reset()

    response = stack.api.post(
        "/api/soap",
        json={
            "service": "AVTransport",
            "action": "SetAVTransportURI",
            "args": args,
            "confirm": True,
        },
    )

    assert response.status_code == 200
    [call] = stack.device.soap_calls
    assert call.args == args


def test_null_argument_is_sent_as_empty_value(stack: Stack) -> None:
    stack.device.reset()

    response = stack.api.post(
        "/api/soap",
        json={
            "service": "AVTransport",
            "action": "SetAVTransportURI",
            "args": {"InstanceID": 0, "CurrentURIMetaData": None},
            "confirm": True,
        },
    )

    assert response.status_code == 200
    [call] = stack.device.soap_calls
    assert call.args == {"InstanceID": "0", "CurrentURIMetaData": ""}


@pytest.mark.parametrize(
    "body",
    [
        {"service": "AVTransport", "action": "Get<Info>"},
        {"service": "AV Transport", "action": "GetTransportInfo"},
        {"service": "AVTransport", "action": "Play", "args": {"Instance ID": 0}},
        {"service": "AVTransport", "action": "Play", "args": {"1st": 0}},
        {"service": "AVTransport", "action": ""},
        {"service": "AVTransport", "action": "GetTransportInfo", "bogus": 1},
        {"action": "GetTransportInfo"},
    ],
    ids=[
        "action-not-xml-name",
        "service-not-xml-name",
        "arg-with-space",
        "arg-starting-with-digit",
        "empty-action",
        "unknown-field",
        "no-service",
    ],
)
def test_invalid_request_is_422_and_not_sent(
    *, stack: Stack, body: dict[str, Any]
) -> None:
    stack.device.reset()

    response = stack.api.post("/api/soap", json=body | {"confirm": True})

    assert response.status_code == 422
    assert stack.device.soap_calls == []


@pytest.mark.parametrize(
    "body",
    [
        b'{"service": "AVTransport", "action": "Seek", "args": {"Target": NaN}, "confirm": true}',
        b'{"service": "AVTransport", "action": "Seek", "args": {"Target": "\\ud800"}, "confirm": true}',
    ],
    ids=["nan", "lone-surrogate"],
)
def test_argument_that_is_not_a_json_value_is_422_and_not_sent(
    *, stack: Stack, body: bytes
) -> None:
    stack.device.reset()

    response = stack.api.post(
        "/api/soap", content=body, headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 422
    assert stack.device.soap_calls == []


def test_service_the_device_does_not_have_is_502(stack: Stack) -> None:
    stack.device.reset()

    response = stack.api.post(
        "/api/soap",
        json={
            "service": "ScheduledRecording",
            "action": "GetSortCapabilities",
            "confirm": True,
        },
    )

    assert response.status_code == 502
    assert stack.device.soap_calls == []
