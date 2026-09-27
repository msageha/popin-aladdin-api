from enum import StrEnum

from pydantic import BaseModel, Field


class PlayMode(StrEnum):
    """AVTransport の再生モード (SetPlayMode の NewPlayMode)。"""

    NORMAL = "NORMAL"
    REPEAT_ONE = "REPEAT_ONE"
    REPEAT_ALL = "REPEAT_ALL"
    SHUFFLE = "SHUFFLE"
    SHUFFLE_NOREPEAT = "SHUFFLE_NOREPEAT"


class LightButton(StrEnum):
    """シーリングライトのボタン。"""

    SWITCH = "switch"
    BRIGHTER = "brighter"
    DARKER = "darker"
    COOLER = "cooler"
    WARMER = "warmer"
    FULL = "full"
    NIGHT = "night"
    ON = "on"
    OFF = "off"
    ECO = "eco"
    SLEEP = "sleep"


class ProjectorKey(StrEnum):
    """プロジェクターのリモコンキー。方向キー (押下 / 離上) とハードキー (単発)。"""

    HOME = "home"
    UP = "up"
    RIGHT = "right"
    DOWN = "down"
    OK = "ok"
    LEFT = "left"
    BACK = "back"
    VOL_UP = "vol_up"
    VOL_DOWN = "vol_down"
    POWER = "power"
    MENU = "menu"


class UpnpService(BaseModel):
    service_type: str = Field(
        description="serviceType URN",
        examples=["urn:schemas-upnp-org:service:AVTransport:1"],
    )
    control_url: str = Field(description="SOAP control の絶対 URL")


class DeviceDescription(BaseModel):
    """UPnP device description の解析結果。services は短い service 名でキー付けする。"""

    friendly_name: str | None = Field(description="friendlyName")
    manufacturer: str | None = Field(description="manufacturer")
    model_name: str | None = Field(description="modelName")
    model_description: str | None = Field(description="modelDescription")
    udn: str | None = Field(description="UDN (Unique Device Name)")
    services: dict[str, UpnpService] = Field(description="service 名 → service")


class DeviceInfo(BaseModel):
    friendly_name: str | None = Field(
        description="UPnP friendly name", examples=["Aladdin 2"]
    )
    manufacturer: str | None = Field(description="製造者", examples=["Plutinosoft LLC"])
    model_name: str | None = Field(
        description="モデル名", examples=["AV Renderer Device"]
    )
    model_description: str | None = Field(description="モデル説明")
    udn: str | None = Field(
        description="Unique Device Name (機体ごとに異なる)",
        examples=["uuid:54F15F164D4F-dmr"],
    )
    services: list[str] = Field(
        description="公開している UPnP service 名",
        examples=[["AVTransport", "ConnectionManager", "RenderingControl"]],
    )
    description_url: str = Field(
        description="device description の URL", examples=["http://172.16.1.113:1481/"]
    )


class TransportInfo(BaseModel):
    state: str | None = Field(
        description="再生状態 (CurrentTransportState)",
        examples=["STOPPED", "PLAYING", "PAUSED_PLAYBACK"],
    )
    status: str | None = Field(
        description="CurrentTransportStatus", examples=["OK", "ERROR_OCCURRED"]
    )
    speed: str | None = Field(description="再生速度 (CurrentSpeed)", examples=["1"])


class PositionInfo(BaseModel):
    track: int = Field(description="現在のトラック番号")
    track_duration: str | None = Field(
        description="トラック長 (H:MM:SS)", examples=["0:03:32"]
    )
    track_duration_seconds: float | None = Field(
        description="トラック長 (秒)", examples=[212.0]
    )
    track_uri: str | None = Field(description="現在のトラック URI")
    track_metadata: str | None = Field(description="現在のトラックの DIDL-Lite")
    rel_time: str | None = Field(description="再生位置 (H:MM:SS)", examples=["0:00:30"])
    rel_time_seconds: float | None = Field(description="再生位置 (秒)", examples=[30.0])
    abs_time: str | None = Field(description="絶対時刻 (多くの機器で NOT_IMPLEMENTED)")


class MediaInfo(BaseModel):
    nr_tracks: int = Field(description="トラック数")
    media_duration: str | None = Field(description="メディア長 (H:MM:SS)")
    current_uri: str | None = Field(description="読み込まれているメディア URI")
    current_uri_metadata: str | None = Field(description="メディアの DIDL-Lite")
    play_medium: str | None = Field(description="PlayMedium", examples=["NETWORK"])


class ProtocolInfo(BaseModel):
    source: list[str] = Field(description="source 側の protocolInfo 一覧")
    sink: list[str] = Field(
        description="sink (受信可能フォーマット) の protocolInfo 一覧"
    )


class RendererStatus(BaseModel):
    """よく参照する状態を 1 回の呼び出しでまとめたもの。"""

    state: str | None = Field(
        description="再生状態", examples=["STOPPED", "PLAYING", "PAUSED_PLAYBACK"]
    )
    status: str | None = Field(description="CurrentTransportStatus", examples=["OK"])
    volume: int = Field(description="マスター音量 (0..100)", examples=[35])
    mute: bool = Field(description="ミュート中か")
    current_uri: str | None = Field(description="読み込まれているメディア URI")
    track_duration_seconds: float | None = Field(
        description="トラック長 (秒)", examples=[212.0]
    )
    position_seconds: float | None = Field(description="再生位置 (秒)", examples=[30.0])
