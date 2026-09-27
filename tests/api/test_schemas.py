import pytest
from pydantic import ValidationError

from popin_aladdin_api.api.schemas import (
    CastRequest,
    KeyRequest,
    LightRequest,
    PlayModeRequest,
    SeekRequest,
    SoapRequest,
    Volume,
)
from popin_aladdin_api.device.models import LightButton, PlayMode, ProjectorKey


def test_volume_range():
    assert Volume.model_validate({"volume": 0}).volume == 0
    assert Volume.model_validate({"volume": 100}).volume == 100
    for bad in (-1, 101):
        with pytest.raises(ValidationError):
            Volume.model_validate({"volume": bad})


def test_seek_rejects_negative_and_infinite():
    assert SeekRequest.model_validate({"seconds": 0}).seconds == 0
    for bad in (-5, float("inf"), "nan"):
        with pytest.raises(ValidationError):
            SeekRequest.model_validate({"seconds": bad})


def test_play_mode_is_enum():
    assert PlayModeRequest.model_validate({"mode": "NORMAL"}).mode is PlayMode.NORMAL
    with pytest.raises(ValidationError):
        PlayModeRequest.model_validate({"mode": "FAST"})


def test_cast_requires_absolute_url():
    ok = CastRequest.model_validate({"uri": "http://192.168.1.50/v.mp4"})
    assert ok.autoplay is True
    assert ok.upnp_class == "object.item.videoItem"
    with pytest.raises(ValidationError):
        CastRequest.model_validate({"uri": "v.mp4"})


def test_light_request_validation():
    ok = LightRequest.model_validate({"button": "brighter", "repeat": 5})
    assert ok.button is LightButton.BRIGHTER
    assert ok.repeat == 5
    assert LightRequest.model_validate({"button": "on"}).repeat == 1
    for bad in ({"button": "strobe"}, {"button": "on", "repeat": 0}):
        with pytest.raises(ValidationError):
            LightRequest.model_validate(bad)


def test_key_request_accepts_dpad_and_hardware_keys():
    assert KeyRequest.model_validate({"button": "up"}).button is ProjectorKey.UP
    assert KeyRequest.model_validate({"button": "back"}).button is ProjectorKey.BACK
    with pytest.raises(ValidationError):
        KeyRequest.model_validate({"button": "rewind"})


def test_soap_request_forbids_extra_and_invalid_names():
    ok = SoapRequest.model_validate(
        {"service": "AVTransport", "action": "GetTransportInfo"}
    )
    assert ok.confirm is False
    assert ok.args == {}
    for bad in (
        {"service": "AVTransport", "action": "X", "bogus": 1},
        {"service": "AVTransport", "action": "Get<Info>"},
        {"service": "AVTransport", "action": "Play", "args": {"Instance ID": 0}},
    ):
        with pytest.raises(ValidationError):
            SoapRequest.model_validate(bad)
