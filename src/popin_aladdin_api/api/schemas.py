from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from ..device.models import LightButton, PlayMode, ProjectorKey
from ..device.renderer import DEFAULT_CAST_TITLE, DEFAULT_UPNP_CLASS

# SOAP の action / 引数名はそのまま XML 要素名になるので、XML の名前として妥当な文字列に限る。
XmlName = Annotated[str, StringConstraints(pattern=r"^[A-Za-z_][A-Za-z0-9_.-]*$")]


class Volume(BaseModel):
    volume: int = Field(
        ge=0, le=100, description="マスター音量 (0..100)", examples=[35]
    )


class Mute(BaseModel):
    mute: bool = Field(description="True でミュート、False で解除", examples=[True])


class SeekRequest(BaseModel):
    seconds: float = Field(
        ge=0,
        allow_inf_nan=False,
        description="先頭からの絶対位置 (秒、REL_TIME)",
        examples=[90],
    )


class PlayModeRequest(BaseModel):
    mode: PlayMode = Field(description="AVTransport の再生モード", examples=["NORMAL"])


class PlayRequest(BaseModel):
    speed: str = Field(
        default="1", description="再生速度 (UPnP の Speed)", examples=["1"]
    )


class CastRequest(BaseModel):
    uri: str = Field(
        pattern=r"^[A-Za-z][A-Za-z0-9+.-]*://",
        description="デバイスの LAN から到達できるメディアの絶対 URL",
        examples=["http://192.168.1.50:8200/video/sample.mp4"],
    )
    title: str = Field(
        default=DEFAULT_CAST_TITLE, description="生成する DIDL-Lite に入れる dc:title"
    )
    upnp_class: str = Field(
        default=DEFAULT_UPNP_CLASS,
        description="DIDL-Lite の upnp:class",
        examples=[
            "object.item.videoItem",
            "object.item.audioItem",
            "object.item.imageItem",
        ],
    )
    metadata: str | None = Field(
        default=None,
        description="DIDL-Lite XML を明示する場合に指定。省略時は title / upnp_class から生成",
    )
    autoplay: bool = Field(default=True, description="読み込み直後に Play を送る")


class LightRequest(BaseModel):
    button: LightButton = Field(
        description="シーリングライトのボタン", examples=["on", "off", "brighter"]
    )
    repeat: int = Field(
        default=1,
        ge=1,
        le=50,
        description="押す回数 (brighter / darker などの段階操作用)",
    )


class KeyRequest(BaseModel):
    button: ProjectorKey = Field(
        description="方向キー (up / down / left / right / ok / home) "
        "またはハードキー (back / menu / vol_up / vol_down / power)",
        examples=["down", "ok", "back"],
    )
    repeat: int = Field(default=1, ge=1, le=50, description="押す回数")


class TextRequest(BaseModel):
    text: str = Field(description="送信する文字列", examples=["hello world"])


class SoapRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service: XmlName = Field(
        description="service の短縮名",
        examples=["AVTransport", "RenderingControl", "ConnectionManager"],
    )
    action: XmlName = Field(
        description="SOAP アクション名", examples=["GetTransportInfo"]
    )
    args: dict[XmlName, Any] = Field(
        default_factory=dict,
        description="アクション引数",
        examples=[{"InstanceID": 0}],
    )
    confirm: bool = Field(
        default=False,
        description="読み取り専用と分かっているアクション以外を送るには true が必須",
    )
