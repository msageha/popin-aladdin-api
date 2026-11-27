"""
再生の操作: POST /api/volume・mute・play・pause・stop・next・previous・seek・play-mode・cast。
"""

import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction
from typing import Any
from xml.etree import ElementTree as ET

import pytest
from hypothesis import example, given, strategies as st

from tests.harness import SoapCall, Stack
from tests.strategies import as_json, non_boolean_json, non_number_json, xml_text

_AVT = "AVTransport"
_RC = "RenderingControl"
_INSTANCE = {"InstanceID": "0"}
_MASTER = {"InstanceID": "0", "Channel": "Master"}
_DIDL_NS = {
    "didl": "urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "upnp": "urn:schemas-upnp-org:metadata-1-0/upnp/",
}
_PLAY_MODES = ["NORMAL", "REPEAT_ONE", "REPEAT_ALL", "SHUFFLE", "SHUFFLE_NOREPEAT"]


# RFC 3986 の hier-part ("//" より後) と query・fragment。pchar は unreserved・sub-delims・":"・"@" と
# percent-encoding。
_PCHAR = r"(?:[A-Za-z0-9._~!$&'()*+,;=:@-]|%[0-9A-Fa-f]{2})"
_URI_AFTER_SCHEME = (
    rf"[A-Za-z0-9.-]+(?::[0-9]{{1,5}})?(?:/{_PCHAR}*)*"
    rf"(?:\?(?:{_PCHAR}|[/?])*)?(?:#(?:{_PCHAR}|[/?])*)?"
)


@given(volume=st.integers(min_value=0, max_value=100))
@example(volume=0)
@example(volume=100)
def test_set_volume_sends_master_volume(*, stack: Stack, volume: int) -> None:
    stack.device.reset()

    response = stack.api.post("/api/volume", json={"volume": volume})

    assert response.status_code == 200
    assert response.json() == {"volume": volume}
    assert stack.device.soap_calls == [
        SoapCall(_RC, "SetVolume", _MASTER | {"DesiredVolume": str(volume)})
    ]


@given(volume=st.integers(max_value=-1) | st.integers(min_value=101))
@example(volume=-1)
@example(volume=101)
def test_set_volume_outside_0_to_100_is_422_and_not_sent(
    *, stack: Stack, volume: int
) -> None:
    stack.device.reset()

    response = stack.api.post("/api/volume", json={"volume": volume})

    assert response.status_code == 422
    assert stack.device.soap_calls == []
    # README「エラー」: 422 の detail には送った値を含めない。
    assert all("input" not in error for error in response.json()["detail"])


# JSON Schema の integer は小数部が 0 の数 (35.0) も含む。
@given(volume=st.integers(min_value=0, max_value=100))
@example(volume=35)
def test_set_volume_to_integer_with_zero_fraction_sends_it_as_integer(
    *, stack: Stack, volume: int
) -> None:
    stack.device.reset()

    response = stack.api.post("/api/volume", json={"volume": float(volume)})

    assert response.status_code == 200
    assert stack.device.soap_calls == [
        SoapCall(_RC, "SetVolume", _MASTER | {"DesiredVolume": str(volume)})
    ]


@given(volume=non_number_json)
@example(volume=True)
@example(volume="35")
def test_set_volume_to_non_number_is_422_and_not_sent(
    *, stack: Stack, volume: object
) -> None:
    stack.device.reset()

    response = stack.api.post("/api/volume", json={"volume": volume})

    assert response.status_code == 422
    assert stack.device.soap_calls == []


@pytest.mark.parametrize(("mute", "desired"), [(True, "1"), (False, "0")])
def test_set_mute_sends_upnp_boolean(*, stack: Stack, mute: bool, desired: str) -> None:
    stack.device.reset()

    response = stack.api.post("/api/mute", json={"mute": mute})

    assert response.status_code == 200
    assert response.json() == {"mute": mute}
    assert stack.device.soap_calls == [
        SoapCall(_RC, "SetMute", _MASTER | {"DesiredMute": desired})
    ]


@given(mute=non_boolean_json)
@example(mute="yes")
@example(mute="false")
@example(mute=0)
def test_set_mute_to_non_boolean_is_422_and_not_sent(
    *, stack: Stack, mute: object
) -> None:
    stack.device.reset()

    response = stack.api.post("/api/mute", json={"mute": mute})

    assert response.status_code == 422
    assert stack.device.soap_calls == []


@pytest.mark.parametrize(
    ("body", "speed"), [(None, "1"), ({}, "1"), ({"speed": "2"}, "2")]
)
def test_play_sends_speed_defaulting_to_normal(
    *, stack: Stack, body: dict[str, str] | None, speed: str
) -> None:
    stack.device.reset()

    response = stack.api.post("/api/play", json=body)

    assert response.status_code == 200
    assert response.json() == {"action": "play", "speed": speed}
    assert stack.device.soap_calls == [
        SoapCall(_AVT, "Play", _INSTANCE | {"Speed": speed})
    ]


@pytest.mark.parametrize(
    ("path", "action"),
    [
        ("/api/pause", "Pause"),
        ("/api/stop", "Stop"),
        ("/api/next", "Next"),
        ("/api/previous", "Previous"),
    ],
)
def test_transport_button_sends_its_action(
    *, stack: Stack, path: str, action: str
) -> None:
    stack.device.reset()

    response = stack.api.post(path)

    assert response.status_code == 200
    assert response.json() == {"action": path.removeprefix("/api/")}
    assert stack.device.soap_calls == [SoapCall(_AVT, action, _INSTANCE)]


@given(seconds=st.floats(min_value=0, allow_nan=False, allow_infinity=False))
@example(seconds=0.0)
@example(seconds=59.5)
@example(seconds=3599.6)
@example(seconds=1e300)
@example(seconds=90)  # JSON の整数も number として受け付ける。
def test_seek_sends_rel_time_target_of_the_position(
    *, stack: Stack, seconds: float
) -> None:
    stack.device.reset()

    response = stack.api.post("/api/seek", json={"seconds": seconds})

    assert response.status_code == 200
    assert response.json() == {"seconds": seconds}
    [call] = stack.device.soap_calls
    assert (call.service, call.action) == (_AVT, "Seek")
    args = call.args
    assert args.keys() == {"InstanceID", "Unit", "Target"}
    assert (args["InstanceID"], args["Unit"]) == ("0", "REL_TIME")
    target = re.fullmatch(r"(\d+):([0-5]\d):([0-5]\d)", args["Target"])
    assert target is not None
    hours, minutes, secs = (int(part) for part in target.groups())
    # 大きな値でも float に丸めずに比べる。
    position = Fraction(hours * 3600 + minutes * 60 + secs)
    assert abs(position - Fraction(seconds)) <= Fraction(1, 2)


@pytest.mark.parametrize(
    "body",
    [
        b'{"seconds": -0.5}',
        b'{"seconds": -1e300}',
        b'{"seconds": NaN}',
        b'{"seconds": Infinity}',
        b'{"seconds": "NaN"}',
        b'{"seconds": "Infinity"}',
        b'{"seconds": "later"}',
        b"{}",
    ],
)
def test_seek_to_negative_or_non_finite_position_is_422_and_not_sent(
    *, stack: Stack, body: bytes
) -> None:
    stack.device.reset()

    response = stack.api.post(
        "/api/seek", content=body, headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 422
    assert stack.device.soap_calls == []


@given(seconds=non_number_json)
@example(seconds=True)
@example(seconds="90")
def test_seek_to_non_number_is_422_and_not_sent(
    *, stack: Stack, seconds: object
) -> None:
    stack.device.reset()

    response = stack.api.post("/api/seek", json={"seconds": seconds})

    assert response.status_code == 422
    assert stack.device.soap_calls == []


@pytest.mark.parametrize("mode", _PLAY_MODES)
def test_play_mode_sends_new_play_mode(*, stack: Stack, mode: str) -> None:
    stack.device.reset()

    response = stack.api.post("/api/play-mode", json={"mode": mode})

    assert response.status_code == 200
    assert response.json() == {"play_mode": mode}
    assert stack.device.soap_calls == [
        SoapCall(_AVT, "SetPlayMode", _INSTANCE | {"NewPlayMode": mode})
    ]


@pytest.mark.parametrize("mode", ["FAST", "normal", ""])
def test_unknown_play_mode_is_422_and_not_sent(*, stack: Stack, mode: str) -> None:
    stack.device.reset()

    response = stack.api.post("/api/play-mode", json={"mode": mode})

    assert response.status_code == 422
    assert stack.device.soap_calls == []


def _didl_item(metadata: str) -> dict[str, Any]:
    """DIDL-Lite の 1 つの item の dc:title・upnp:class・res と res の protocolInfo。"""
    root = ET.fromstring(metadata)
    assert root.tag == f"{{{_DIDL_NS['didl']}}}DIDL-Lite"
    [item] = root.findall("didl:item", _DIDL_NS)
    res = item.find("didl:res", _DIDL_NS)
    assert res is not None
    return {
        "title": item.findtext("dc:title", namespaces=_DIDL_NS),
        "class": item.findtext("upnp:class", namespaces=_DIDL_NS),
        "res": res.text or "",
        # protocolInfo は "<protocol>:<network>:<contentFormat>:<additionalInfo>"。
        "valid_protocol_info": len(res.get("protocolInfo", "").split(":")) == 4,
    }


def test_cast_loads_uri_with_generated_metadata_and_plays(stack: Stack) -> None:
    stack.device.reset()
    uri = "http://192.0.2.50:8200/video/sample.mp4"

    response = stack.api.post("/api/cast", json={"uri": uri})

    assert response.status_code == 200
    assert response.json() == {"uri": uri, "autoplay": True}
    [load, play] = stack.device.soap_calls
    assert (load.service, load.action) == (_AVT, "SetAVTransportURI")
    load_args = load.args
    assert (load_args["InstanceID"], load_args["CurrentURI"]) == ("0", uri)
    assert _didl_item(load_args["CurrentURIMetaData"]) == {
        "title": "popin-aladdin-api",
        "class": "object.item.videoItem",
        "res": uri,
        "valid_protocol_info": True,
    }
    assert play == SoapCall(_AVT, "Play", _INSTANCE | {"Speed": "1"})


def test_cast_without_autoplay_only_loads_uri(stack: Stack) -> None:
    stack.device.reset()
    uri = "http://192.0.2.50/a.mp3"

    response = stack.api.post("/api/cast", json={"uri": uri, "autoplay": False})

    assert response.status_code == 200
    assert response.json() == {"uri": uri, "autoplay": False}
    assert stack.device.actions == ["SetAVTransportURI"]


@given(autoplay=non_boolean_json)
@example(autoplay="no")
@example(autoplay="false")
@example(autoplay=0)
def test_cast_with_non_boolean_autoplay_is_422_and_not_sent(
    *, stack: Stack, autoplay: object
) -> None:
    stack.device.reset()

    response = stack.api.post(
        "/api/cast", json={"uri": "http://192.0.2.50/a.mp4", "autoplay": autoplay}
    )

    assert response.status_code == 422
    assert stack.device.soap_calls == []


def test_cast_sends_given_metadata_unchanged(stack: Stack) -> None:
    stack.device.reset()
    metadata = '<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/"><item id="1"/></DIDL-Lite>'

    response = stack.api.post(
        "/api/cast",
        json={"uri": "http://192.0.2.50/a.mp4", "metadata": metadata, "title": "x"},
    )

    assert response.status_code == 200
    [load, _] = stack.device.soap_calls
    assert load.args["CurrentURIMetaData"] == metadata


@given(
    scheme=st.from_regex(r"[A-Za-z][A-Za-z0-9+.-]{0,8}", fullmatch=True),
    rest=st.from_regex(_URI_AFTER_SCHEME, fullmatch=True),
    title=xml_text,
    upnp_class=xml_text,
)
@example(scheme="http", rest="h/a?b=1&c='d'", title="<&>\"'", upnp_class="a&b")
@example(
    scheme="http",
    rest="192.0.2.50:8200/v.mp4",
    title="line\r\nbreak\r",
    upnp_class="\t",
)
def test_cast_metadata_carries_uri_title_and_class_unchanged(
    *, stack: Stack, scheme: str, rest: str, title: str, upnp_class: str
) -> None:
    stack.device.reset()
    uri = f"{scheme}://{rest}"

    response = stack.api.post(
        "/api/cast",
        json={"uri": uri, "title": title, "upnp_class": upnp_class, "autoplay": False},
    )

    assert response.status_code == 200
    [load] = stack.device.soap_calls
    assert (load.service, load.action) == (_AVT, "SetAVTransportURI")
    load_args = load.args
    assert load_args["CurrentURI"] == uri
    assert as_json(_didl_item(load_args["CurrentURIMetaData"])) == as_json(
        {"title": title, "class": upnp_class, "res": uri, "valid_protocol_info": True}
    )


@pytest.mark.parametrize(
    "uri", ["sample.mp4", "/video/sample.mp4", "//host/a.mp4", "1http://h/a", ""]
)
def test_cast_of_relative_uri_is_422_and_not_sent(*, stack: Stack, uri: str) -> None:
    stack.device.reset()

    response = stack.api.post("/api/cast", json={"uri": uri})

    assert response.status_code == 422
    assert stack.device.soap_calls == []


def test_key_during_cast_waits_until_cast_finishes(stack: Stack) -> None:
    stack.device.reset()
    # 読み込みの応答を保留し、その間に別の制御面 (UDP のキー入力) の操作を送る。
    loaded = threading.Event()
    stack.device.soap_gates["SetAVTransportURI"] = loaded
    with ThreadPoolExecutor(max_workers=2) as executor:
        cast = executor.submit(
            stack.api.post, "/api/cast", json={"uri": "http://192.0.2.50/a.mp4"}
        )
        stack.device.wait_for_soap_calls(count=1)
        key = executor.submit(stack.api.post, "/api/key", json={"button": "back"})
        # キー入力の要求が API に届くまでの時間。API のタイムアウト (1 秒) より前に応答を返す。
        time.sleep(0.2)
        # 読み込みの応答を待つ間は、キー入力をデバイスへ送らない。
        keys_during_cast = stack.device.received_keys()
        loaded.set()

        assert cast.result().status_code == 200
        assert key.result().status_code == 200
    assert keys_during_cast == []
    assert stack.device.actions == ["SetAVTransportURI", "Play"]
    assert stack.device.received_keys() == ["KEYPRESSES:48"]


def test_request_during_cast_waits_until_cast_finishes(stack: Stack) -> None:
    stack.device.reset()
    # 読み込みの応答を遅らせ、読み込みが届いてから応答するまでの間に別の操作を送る。
    stack.device.soap_delays["SetAVTransportURI"] = 0.5
    with ThreadPoolExecutor(max_workers=1) as executor:
        cast = executor.submit(
            stack.api.post, "/api/cast", json={"uri": "http://192.0.2.50/a.mp4"}
        )
        stack.device.wait_for_soap_calls(count=1)

        stop = stack.api.post("/api/stop")

        assert cast.result().status_code == 200
    assert stop.status_code == 200
    assert stack.device.actions == ["SetAVTransportURI", "Play", "Stop"]
