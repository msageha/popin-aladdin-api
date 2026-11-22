import json
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from popin_aladdin_api.device.models import LightButton, PlayMode, ProjectorKey
from popin_aladdin_api.device.renderer import MAX_VOLUME

# SOAP の action / 引数名はそのまま XML 要素名になるので、XML の名前として妥当な文字列に限る。
type XmlName = Annotated[str, StringConstraints(pattern=r"^[A-Za-z_][A-Za-z0-9_.-]*$")]


class _Request(BaseModel):
    """API への要求の本文。"""

    @model_validator(mode="before")
    @classmethod
    def _require_json_values(cls, data: object) -> object:
        # 本文の parser は孤立した surrogate (U+D800 など) と NaN・Infinity も通すが、前者は UTF-8 で
        # 表せず、後者は JSON の値ではないので、デバイスへ送る前に拒否する。JSON の object でない本文は
        # モデルの検証に任せる。
        if isinstance(data, dict):
            try:
                json.dumps(data, ensure_ascii=False, allow_nan=False).encode()
            except ValueError as err:
                raise ValueError(
                    "request must not contain NaN, Infinity or unpaired surrogates"
                ) from err
        return data


class Volume(_Request):
    volume: int = Field(
        ge=0,
        le=MAX_VOLUME,
        description=f"マスター音量 (0..{MAX_VOLUME})",
        examples=[35],
    )


class Mute(_Request):
    mute: bool = Field(description="True でミュート、False で解除", examples=[True])


class SeekRequest(_Request):
    seconds: float = Field(
        ge=0,
        allow_inf_nan=False,
        description="先頭からの絶対位置 (秒、REL_TIME)",
        examples=[90],
    )


class PlayModeRequest(_Request):
    mode: PlayMode = Field(description="AVTransport の再生モード", examples=["NORMAL"])


class PlayRequest(_Request):
    speed: str = Field(
        default="1", description="再生速度 (UPnP の Speed)", examples=["1"]
    )


class CastRequest(_Request):
    uri: str = Field(
        pattern=r"^[A-Za-z][A-Za-z0-9+.-]*://",
        description="デバイスの LAN から到達できるメディアの絶対 URL",
        examples=["http://192.168.1.50:8200/video/sample.mp4"],
    )
    title: str = Field(
        default="popin-aladdin-api", description="生成する DIDL-Lite に入れる dc:title"
    )
    upnp_class: str = Field(
        default="object.item.videoItem",
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


class LightRequest(_Request):
    button: LightButton = Field(
        description="シーリングライトのボタン", examples=["on", "off", "brighter"]
    )
    repeat: int = Field(
        default=1,
        ge=1,
        le=50,
        description="押す回数 (brighter / darker などの段階操作用)",
    )


class KeyRequest(_Request):
    button: ProjectorKey = Field(
        description="方向キー (up / down / left / right / ok / home)、フォーカス調整 "
        "(focus_plus / focus_minus)、長押し (home_long / menu_long)、ハードキー "
        "(back / menu / vol_up / vol_down / power / settings / netflix / youtube / "
        "prime_video / custom / custom_long)",
        examples=["down", "ok", "back", "youtube"],
    )
    repeat: int = Field(default=1, ge=1, le=50, description="押す回数")


class TextRequest(_Request):
    text: str = Field(description="送信する文字列", examples=["hello world"])


class DeeplinkRequest(_Request):
    url: str = Field(
        min_length=1,
        description="デバイスで開く deeplink (アプリの URL scheme / intent URL)",
        examples=["https://www.youtube.com/tv", "tver://"],
    )


class PowerOffRequest(_Request):
    confirm: bool = Field(
        default=False,
        description="電源を切るには true が必須。切った後はこの API から再点灯できない",
    )


class SoapRequest(_Request):
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
