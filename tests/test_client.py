import pytest

from aladdin.client import AladdinClient
from aladdin.exceptions import AladdinError
from aladdin.soap import DeviceDescription, ServiceRef

pytestmark = pytest.mark.unit


def _client_with_services() -> AladdinClient:
    client = AladdinClient("http://unit", upnp_port=1481)
    client._description = DeviceDescription(
        friendly_name="Aladdin 2",
        manufacturer="Plutinosoft LLC",
        model_name="AV Renderer Device",
        model_description=None,
        udn="uuid:54F15F164D4F-dmr",
        services={
            "AVTransport": ServiceRef(
                "urn:schemas-upnp-org:service:AVTransport:1",
                "http://unit:1481/AVTransport/control.xml",
                "http://unit:1481/AVTransport/scpd.xml",
                "http://unit:1481/AVTransport/event.xml",
            ),
            "RenderingControl": ServiceRef(
                "urn:schemas-upnp-org:service:RenderingControl:1",
                "http://unit:1481/RenderingControl/control.xml",
                "http://unit:1481/RenderingControl/scpd.xml",
                "http://unit:1481/RenderingControl/event.xml",
            ),
        },
    )
    return client


def test_description_url_swaps_in_upnp_port():
    client = AladdinClient("http://172.16.1.113", upnp_port=1481)
    assert client.description_url == "http://172.16.1.113:1481/"


def test_transport_info_maps_response(monkeypatch):
    client = _client_with_services()
    captured = {}

    def fake_invoke(service, action, args=None):
        captured.update(service=service, action=action, args=args)
        return {
            "CurrentTransportState": "PLAYING",
            "CurrentTransportStatus": "OK",
            "CurrentSpeed": "1",
        }

    monkeypatch.setattr(client, "invoke", fake_invoke)
    info = client.transport_info()
    assert info == {"state": "PLAYING", "status": "OK", "speed": "1"}
    assert captured["service"] == "AVTransport"
    assert captured["action"] == "GetTransportInfo"
    assert captured["args"] == {"InstanceID": 0}


def test_position_info_decodes_durations(monkeypatch):
    client = _client_with_services()
    monkeypatch.setattr(
        client,
        "invoke",
        lambda *a, **k: {
            "Track": "1",
            "TrackDuration": "0:03:32",
            "TrackURI": "http://h/v.mp4",
            "TrackMetaData": "",
            "RelTime": "0:00:30",
            "AbsTime": "0:00:30",
        },
    )
    pos = client.position_info()
    assert pos["track"] == 1
    assert pos["track_duration_seconds"] == 212.0
    assert pos["rel_time_seconds"] == 30.0
    assert pos["track_uri"] == "http://h/v.mp4"
    assert pos["track_metadata"] is None  # empty string -> None


def test_get_volume_and_mute(monkeypatch):
    client = _client_with_services()
    monkeypatch.setattr(client, "invoke", lambda *a, **k: {"CurrentVolume": "35"})
    assert client.get_volume() == 35

    monkeypatch.setattr(client, "invoke", lambda *a, **k: {"CurrentMute": "1"})
    assert client.get_mute() is True
    monkeypatch.setattr(client, "invoke", lambda *a, **k: {"CurrentMute": "0"})
    assert client.get_mute() is False


def test_set_volume_validates_range():
    client = _client_with_services()
    with pytest.raises(AladdinError):
        client.set_volume(101)
    with pytest.raises(AladdinError):
        client.set_volume(-1)


def test_set_volume_builds_args(monkeypatch):
    client = _client_with_services()
    captured = {}
    monkeypatch.setattr(
        client,
        "invoke",
        lambda service, action, args=None: captured.update(
            service=service, action=action, args=args
        ),
    )
    client.set_volume(40)
    assert captured["service"] == "RenderingControl"
    assert captured["action"] == "SetVolume"
    assert captured["args"] == {
        "InstanceID": 0,
        "Channel": "Master",
        "DesiredVolume": 40,
    }


def test_seek_formats_target(monkeypatch):
    client = _client_with_services()
    captured = {}
    monkeypatch.setattr(
        client,
        "invoke",
        lambda service, action, args=None: captured.update(args=args),
    )
    client.seek(90)
    assert captured["args"]["Unit"] == "REL_TIME"
    assert captured["args"]["Target"] == "0:01:30"


def test_set_play_mode_rejects_unknown():
    client = _client_with_services()
    with pytest.raises(AladdinError):
        client.set_play_mode("BOGUS")


def test_set_av_transport_uri_generates_metadata(monkeypatch):
    client = _client_with_services()
    calls = []
    monkeypatch.setattr(
        client,
        "invoke",
        lambda service, action, args=None: calls.append((action, args)),
    )
    client.set_av_transport_uri("http://h/v.mp4", autoplay=True)
    actions = [c[0] for c in calls]
    assert actions == ["SetAVTransportURI", "Play"]
    set_args = calls[0][1]
    assert set_args["CurrentURI"] == "http://h/v.mp4"
    assert "DIDL-Lite" in set_args["CurrentURIMetaData"]


def test_missing_service_raises(monkeypatch):
    client = _client_with_services()
    client._description.services.pop("RenderingControl")
    with pytest.raises(AladdinError):
        client._service("RenderingControl")
