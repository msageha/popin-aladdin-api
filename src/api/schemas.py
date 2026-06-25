from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from aladdin.client import PLAY_MODES
from aladdin.remote import (
    CEILING_BUTTONS,
    PROJECTOR_KEYS,
    PROJECTOR_STATELESS_KEYS,
)

_LIGHT_BUTTONS = tuple(CEILING_BUTTONS)
_KEY_BUTTONS = tuple(PROJECTOR_KEYS) + tuple(PROJECTOR_STATELESS_KEYS)


class DeviceInfo(BaseModel):
    friendly_name: str | None = Field(
        default=None, description="UPnP friendly name", examples=["Aladdin 2"]
    )
    manufacturer: str | None = Field(default=None, examples=["Plutinosoft LLC"])
    model_name: str | None = Field(default=None, examples=["AV Renderer Device"])
    model_description: str | None = Field(default=None)
    udn: str | None = Field(
        default=None,
        description="Unique Device Name (UUID)",
        examples=["uuid:54F15F164D4F-dmr"],
    )
    services: list[str] = Field(
        default_factory=list,
        description="UPnP services the renderer exposes",
        examples=[["AVTransport", "ConnectionManager", "RenderingControl"]],
    )
    description_url: str | None = Field(
        default=None, examples=["http://172.16.1.113:1481/"]
    )


class Status(BaseModel):
    state: str | None = Field(
        default=None,
        description="Transport state",
        examples=["STOPPED", "PLAYING", "PAUSED_PLAYBACK"],
    )
    status: str | None = Field(default=None, examples=["OK"])
    volume: int | None = Field(default=None, ge=0, le=100, examples=[35])
    mute: bool | None = Field(default=None)
    current_uri: str | None = Field(default=None)
    track_duration_seconds: float | None = Field(default=None, examples=[212.0])
    position_seconds: float | None = Field(default=None, examples=[12.0])


class TransportInfo(BaseModel):
    state: str | None = None
    status: str | None = None
    speed: str | None = None


class PositionInfo(BaseModel):
    track: int | None = None
    track_duration: str | None = None
    track_duration_seconds: float | None = None
    track_uri: str | None = None
    track_metadata: str | None = None
    rel_time: str | None = None
    rel_time_seconds: float | None = None
    abs_time: str | None = None


class MediaInfo(BaseModel):
    nr_tracks: int | None = None
    media_duration: str | None = None
    current_uri: str | None = None
    current_uri_metadata: str | None = None
    play_medium: str | None = None


class VolumeRequest(BaseModel):
    volume: int = Field(
        description="Master volume, 0..100", ge=0, le=100, examples=[35]
    )


class MuteRequest(BaseModel):
    mute: bool = Field(description="True to mute, False to unmute", examples=[True])


class SeekRequest(BaseModel):
    seconds: float = Field(
        description="Absolute position in seconds (REL_TIME)", ge=0, examples=[90]
    )


class PlayModeRequest(BaseModel):
    mode: str = Field(
        description="AVTransport play mode",
        examples=["NORMAL"],
    )

    @field_validator("mode")
    @classmethod
    def _validate_mode(cls, v: str) -> str:
        if v not in PLAY_MODES:
            raise ValueError(f"mode must be one of {PLAY_MODES}")
        return v


class PlayRequest(BaseModel):
    speed: str = Field(default="1", description="Playback speed", examples=["1"])


class CastRequest(BaseModel):
    uri: str = Field(
        description="Media URL to load and play on the device",
        examples=["http://192.168.1.50:8200/video/sample.mp4"],
    )
    title: str = Field(
        default="popin-aladdin-api",
        description="Title placed in the generated DIDL-Lite metadata",
    )
    upnp_class: str = Field(
        default="object.item.videoItem",
        description="DIDL-Lite upnp:class for the item",
        examples=[
            "object.item.videoItem",
            "object.item.audioItem",
            "object.item.imageItem",
        ],
    )
    metadata: str | None = Field(
        default=None,
        description="Explicit DIDL-Lite metadata; generated from title/uri if omitted",
    )
    autoplay: bool = Field(
        default=True, description="Send Play immediately after loading the URI"
    )

    @field_validator("uri")
    @classmethod
    def _validate_uri(cls, v: str) -> str:
        if "://" not in v:
            raise ValueError("uri must be an absolute URL, e.g. http://host/file.mp4")
        return v


class LightRequest(BaseModel):
    button: str = Field(
        description="Ceiling-light button",
        examples=["on", "off", "brighter", "darker", "cooler", "warmer"],
    )
    repeat: int = Field(
        default=1,
        ge=1,
        le=50,
        description="Repeat the press N times (e.g. step brightness)",
    )

    @field_validator("button")
    @classmethod
    def _validate_button(cls, v: str) -> str:
        if v not in _LIGHT_BUTTONS:
            raise ValueError(f"button must be one of {_LIGHT_BUTTONS}")
        return v


class KeyRequest(BaseModel):
    button: str = Field(
        description="Projector key: D-pad (up/down/left/right/ok/home) or "
        "hardware (back/menu/vol_up/vol_down/power)",
        examples=["up", "down", "left", "right", "ok", "back"],
    )
    repeat: int = Field(default=1, ge=1, le=50, description="Repeat the press N times")

    @field_validator("button")
    @classmethod
    def _validate_button(cls, v: str) -> str:
        if v not in _KEY_BUTTONS:
            raise ValueError(f"button must be one of {_KEY_BUTTONS}")
        return v


class TextRequest(BaseModel):
    text: str = Field(
        description="Text to type into the focused on-screen input",
        examples=["hello world"],
    )


class SoapRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service: str = Field(
        description="Short service name",
        examples=["AVTransport", "RenderingControl", "ConnectionManager"],
    )
    action: str = Field(description="SOAP action name", examples=["GetTransportInfo"])
    args: dict[str, Any] = Field(
        default_factory=dict,
        description="Action arguments",
        examples=[{"InstanceID": 0}],
    )
    confirm: bool = Field(
        default=False,
        description="Must be true to send a Set*/control action to the device",
    )
