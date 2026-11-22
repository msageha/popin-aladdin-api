"""再生状態の読み取り: GET /api/info・status・transport・position・media・protocol-info・volume・mute。"""

from pathlib import Path

import pytest
from hypothesis import example, given, strategies as st

from tests.harness import DEVICE_FIELDS, UDN, SoapCall, Stack, serve_stack


def test_info_reports_device_description(stack: Stack) -> None:
    stack.device.reset()

    response = stack.api.get("/api/info")

    assert response.status_code == 200
    info = response.json()
    assert sorted(info.pop("services")) == [
        "AVTransport",
        "ConnectionManager",
        "RenderingControl",
    ]
    assert info == {
        "friendly_name": DEVICE_FIELDS["friendlyName"],
        "manufacturer": DEVICE_FIELDS["manufacturer"],
        "model_name": DEVICE_FIELDS["modelName"],
        "model_description": DEVICE_FIELDS["modelDescription"],
        "udn": UDN,
        "description_url": f"http://127.0.0.1:{stack.device.upnp_port}/",
    }


def test_device_description_is_fetched_once_per_process(tmp_path: Path) -> None:
    # 共有の API サーバーは取得済みなので、まだ取得していない API サーバーで確かめる。
    with serve_stack(tmp_path / "uvicorn.log") as stack:
        for path in ["/api/info", "/api/status", "/api/volume", "/api/protocol-info"]:
            assert stack.api.get(path).status_code == 200

    assert stack.device.description_requests == 1


def test_status_aggregates_transport_volume_mute_media_and_position(
    stack: Stack,
) -> None:
    stack.device.reset()
    outputs = stack.device.soap_outputs
    outputs["GetTransportInfo"] |= {
        "CurrentTransportState": "PAUSED_PLAYBACK",
        "CurrentTransportStatus": "OK",
    }
    outputs["GetVolume"] = {"CurrentVolume": "42"}
    outputs["GetMute"] = {"CurrentMute": "1"}
    outputs["GetMediaInfo"] |= {"CurrentURI": "http://192.0.2.50/a.mp4"}
    outputs["GetPositionInfo"] |= {"TrackDuration": "1:02:03", "RelTime": "0:00:45"}

    response = stack.api.get("/api/status")

    assert response.status_code == 200
    assert response.json() == {
        "state": "PAUSED_PLAYBACK",
        "status": "OK",
        "volume": 42,
        "mute": True,
        "current_uri": "http://192.0.2.50/a.mp4",
        "track_duration_seconds": 3723.0,
        "position_seconds": 45.0,
    }
    # 各値を、その値を持つ service から読む (読む順序は決まっていない)。
    assert sorted((c.service, c.action) for c in stack.device.soap_calls) == [
        ("AVTransport", "GetMediaInfo"),
        ("AVTransport", "GetPositionInfo"),
        ("AVTransport", "GetTransportInfo"),
        ("RenderingControl", "GetMute"),
        ("RenderingControl", "GetVolume"),
    ]


def test_status_fails_with_502_when_any_part_fails(stack: Stack) -> None:
    stack.device.reset()
    stack.device.soap_outputs["GetMute"] = {"CurrentMute": "maybe"}

    response = stack.api.get("/api/status")

    assert response.status_code == 502


def test_transport_reports_state_status_and_speed(stack: Stack) -> None:
    stack.device.reset()
    stack.device.soap_outputs["GetTransportInfo"] = {
        "CurrentTransportState": "STOPPED",
        "CurrentTransportStatus": "ERROR_OCCURRED",
        "CurrentSpeed": "1",
    }

    response = stack.api.get("/api/transport")

    assert response.status_code == 200
    assert response.json() == {
        "state": "STOPPED",
        "status": "ERROR_OCCURRED",
        "speed": "1",
    }
    assert stack.device.soap_calls == [
        SoapCall("AVTransport", "GetTransportInfo", {"InstanceID": "0"})
    ]


def test_position_reports_track_and_times(stack: Stack) -> None:
    stack.device.reset()
    stack.device.soap_outputs["GetPositionInfo"] = {
        "Track": "3",
        "TrackDuration": "0:03:32",
        "TrackMetaData": "<DIDL-Lite/>",
        "TrackURI": "http://192.0.2.50/a.mp4",
        "RelTime": "0:00:30.500",
        "AbsTime": "NOT_IMPLEMENTED",
    }

    response = stack.api.get("/api/position")

    assert response.status_code == 200
    assert response.json() == {
        "track": 3,
        "track_duration": "0:03:32",
        "track_duration_seconds": 212.0,
        "track_uri": "http://192.0.2.50/a.mp4",
        "track_metadata": "<DIDL-Lite/>",
        "rel_time": "0:00:30.500",
        "rel_time_seconds": 30.5,
        "abs_time": "NOT_IMPLEMENTED",
    }


def test_position_without_media_has_no_seconds_or_uri(stack: Stack) -> None:
    stack.device.reset()
    stack.device.soap_outputs["GetPositionInfo"] = {
        "Track": "0",
        "TrackDuration": "NOT_IMPLEMENTED",
        "TrackMetaData": "",
        "TrackURI": "",
        "RelTime": "NOT_IMPLEMENTED",
        "AbsTime": "NOT_IMPLEMENTED",
    }

    response = stack.api.get("/api/position")

    assert response.status_code == 200
    position = response.json()
    assert position["track_duration_seconds"] is None
    assert position["rel_time_seconds"] is None
    assert position["track_uri"] is None
    assert position["track_metadata"] is None


# 仕様は位置の値の形式が崩れたときの秒数を決めていないが、モデルの秒数の項目は null を取り、
# 元の文字列は秒数の付かない項目で返る。
@pytest.mark.parametrize("reported", ["", "later", "1:xx:00"])
def test_position_that_is_not_a_duration_has_no_seconds(
    *, stack: Stack, reported: str
) -> None:
    stack.device.reset()
    stack.device.soap_outputs["GetPositionInfo"] |= {
        "TrackDuration": reported,
        "RelTime": reported,
    }

    response = stack.api.get("/api/position")

    assert response.status_code == 200
    position = response.json()
    assert (position["track_duration"], position["rel_time"]) == (reported, reported)
    assert position["track_duration_seconds"] is None
    assert position["rel_time_seconds"] is None


@given(
    hours=st.integers(min_value=0, max_value=10_000),
    minutes=st.integers(min_value=0, max_value=59),
    seconds=st.integers(min_value=0, max_value=59),
    fraction=st.none() | st.from_regex(r"[0-9]{1,6}", fullmatch=True),
)
@example(hours=0, minutes=0, seconds=0, fraction=None)
@example(hours=100, minutes=59, seconds=59, fraction="999")
def test_position_converts_upnp_durations_to_seconds(
    *, stack: Stack, hours: int, minutes: int, seconds: int, fraction: str | None
) -> None:
    stack.device.reset()
    duration = f"{hours}:{minutes:02d}:{seconds:02d}"
    if fraction is not None:
        duration += f".{fraction}"
    stack.device.soap_outputs["GetPositionInfo"] |= {
        "TrackDuration": duration,
        "RelTime": duration,
    }

    response = stack.api.get("/api/position")

    assert response.status_code == 200
    expected = hours * 3600 + minutes * 60 + seconds + float(f"0.{fraction or 0}")
    # 小数秒の誤差を見逃さないよう、float の丸めの分だけを許す。
    exact = pytest.approx(expected, rel=0, abs=1e-6)
    assert response.json()["track_duration_seconds"] == exact
    assert response.json()["rel_time_seconds"] == exact


def test_media_reports_current_media(stack: Stack) -> None:
    stack.device.reset()
    stack.device.soap_outputs["GetMediaInfo"] = {
        "NrTracks": "1",
        "MediaDuration": "0:03:32",
        "CurrentURI": "http://192.0.2.50/a.mp4",
        "CurrentURIMetaData": "<DIDL-Lite/>",
        "PlayMedium": "NETWORK",
    }

    response = stack.api.get("/api/media")

    assert response.status_code == 200
    assert response.json() == {
        "nr_tracks": 1,
        "media_duration": "0:03:32",
        "current_uri": "http://192.0.2.50/a.mp4",
        "current_uri_metadata": "<DIDL-Lite/>",
        "play_medium": "NETWORK",
    }


def test_protocol_info_lists_source_and_sink_entries(stack: Stack) -> None:
    stack.device.reset()
    stack.device.soap_outputs["GetProtocolInfo"] = {
        "Source": "",
        "Sink": "http-get:*:video/mp4:*,http-get:*:audio/mpeg:*",
    }

    response = stack.api.get("/api/protocol-info")

    assert response.status_code == 200
    assert response.json() == {
        "source": [],
        "sink": ["http-get:*:video/mp4:*", "http-get:*:audio/mpeg:*"],
    }


@pytest.mark.parametrize("volume", [0, 35, 100])
def test_volume_reports_master_volume(*, stack: Stack, volume: int) -> None:
    stack.device.reset()
    stack.device.soap_outputs["GetVolume"] = {"CurrentVolume": str(volume)}

    response = stack.api.get("/api/volume")

    assert response.status_code == 200
    assert response.json() == {"volume": volume}
    assert stack.device.soap_calls == [
        SoapCall(
            "RenderingControl", "GetVolume", {"InstanceID": "0", "Channel": "Master"}
        )
    ]


@pytest.mark.parametrize("reported", ["-1", "101", "loud", ""])
def test_volume_outside_0_to_100_from_device_is_502(
    *, stack: Stack, reported: str
) -> None:
    stack.device.reset()
    stack.device.soap_outputs["GetVolume"] = {"CurrentVolume": reported}

    response = stack.api.get("/api/volume")

    assert response.status_code == 502


# UPnP の boolean は 1 / true / yes と 0 / false / no で表される。
@pytest.mark.parametrize(
    ("reported", "mute"),
    [
        ("1", True),
        ("true", True),
        ("yes", True),
        ("0", False),
        ("false", False),
        ("no", False),
    ],
)
def test_mute_reads_upnp_boolean(*, stack: Stack, reported: str, mute: bool) -> None:
    stack.device.reset()
    stack.device.soap_outputs["GetMute"] = {"CurrentMute": reported}

    response = stack.api.get("/api/mute")

    assert response.status_code == 200
    assert response.json() == {"mute": mute}
    assert stack.device.soap_calls == [
        SoapCall(
            "RenderingControl", "GetMute", {"InstanceID": "0", "Channel": "Master"}
        )
    ]


@pytest.mark.parametrize("reported", ["2", "maybe", ""])
def test_mute_that_is_not_a_boolean_is_502(*, stack: Stack, reported: str) -> None:
    stack.device.reset()
    stack.device.soap_outputs["GetMute"] = {"CurrentMute": reported}

    response = stack.api.get("/api/mute")

    assert response.status_code == 502
