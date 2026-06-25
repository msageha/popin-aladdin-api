import pytest
from pydantic import ValidationError

from api.schemas import (
    CastRequest,
    DeviceInfo,
    KeyRequest,
    LightRequest,
    PlayModeRequest,
    SeekRequest,
    SoapRequest,
    Status,
    TextRequest,
    VolumeRequest,
)

pytestmark = pytest.mark.unit


def test_device_info_defaults_optional():
    info = DeviceInfo.model_validate({"friendly_name": "Aladdin 2"})
    assert info.friendly_name == "Aladdin 2"
    assert info.manufacturer is None
    assert info.services == []


def test_status_roundtrip():
    status = Status.model_validate(
        {
            "state": "PLAYING",
            "status": "OK",
            "volume": 35,
            "mute": False,
            "current_uri": "http://h/v.mp4",
            "track_duration_seconds": 212.0,
            "position_seconds": 30.0,
        }
    )
    assert status.volume == 35
    assert status.state == "PLAYING"


def test_volume_request_range():
    assert VolumeRequest.model_validate({"volume": 0}).volume == 0
    assert VolumeRequest.model_validate({"volume": 100}).volume == 100
    with pytest.raises(ValidationError):
        VolumeRequest.model_validate({"volume": 101})
    with pytest.raises(ValidationError):
        VolumeRequest.model_validate({"volume": -1})


def test_seek_request_non_negative():
    assert SeekRequest.model_validate({"seconds": 0}).seconds == 0
    with pytest.raises(ValidationError):
        SeekRequest.model_validate({"seconds": -5})


def test_play_mode_validation():
    assert PlayModeRequest.model_validate({"mode": "NORMAL"}).mode == "NORMAL"
    with pytest.raises(ValidationError):
        PlayModeRequest.model_validate({"mode": "FAST"})


def test_cast_request_requires_absolute_url():
    ok = CastRequest.model_validate({"uri": "http://192.168.1.50/v.mp4"})
    assert ok.autoplay is True
    assert ok.upnp_class == "object.item.videoItem"
    with pytest.raises(ValidationError):
        CastRequest.model_validate({"uri": "v.mp4"})


def test_light_request_validation():
    ok = LightRequest.model_validate({"button": "brighter", "repeat": 5})
    assert ok.button == "brighter"
    assert ok.repeat == 5
    assert LightRequest.model_validate({"button": "on"}).repeat == 1
    with pytest.raises(ValidationError):
        LightRequest.model_validate({"button": "strobe"})
    with pytest.raises(ValidationError):
        LightRequest.model_validate({"button": "on", "repeat": 0})


def test_key_request_validation():
    assert KeyRequest.model_validate({"button": "up"}).button == "up"
    assert KeyRequest.model_validate({"button": "back"}).button == "back"
    with pytest.raises(ValidationError):
        KeyRequest.model_validate({"button": "rewind"})


def test_text_request():
    assert TextRequest.model_validate({"text": "hello"}).text == "hello"


def test_soap_request_forbids_extra():
    ok = SoapRequest.model_validate(
        {"service": "AVTransport", "action": "GetTransportInfo"}
    )
    assert ok.confirm is False
    assert ok.args == {}
    with pytest.raises(ValidationError):
        SoapRequest.model_validate(
            {"service": "AVTransport", "action": "X", "bogus": 1}
        )
