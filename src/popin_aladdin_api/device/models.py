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
    """プロジェクターのリモコンキー。

    方向キーは押下 → 離上、フォーカス調整は押下と離上を連続送信、それ以外は単発。
    ``home_long`` / ``menu_long`` は公式アプリの長押しに相当する。
    """

    HOME = "home"
    UP = "up"
    RIGHT = "right"
    DOWN = "down"
    OK = "ok"
    LEFT = "left"
    FOCUS_PLUS = "focus_plus"
    FOCUS_MINUS = "focus_minus"
    HOME_LONG = "home_long"
    BACK = "back"
    VOL_UP = "vol_up"
    VOL_DOWN = "vol_down"
    POWER = "power"
    MENU = "menu"
    MENU_LONG = "menu_long"
    SETTINGS = "settings"
    NETFLIX = "netflix"
    YOUTUBE = "youtube"
    PRIME_VIDEO = "prime_video"
    CUSTOM = "custom"
    CUSTOM_LONG = "custom_long"


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


class RemoteVersion(BaseModel):
    """TCP 制御プロトコルの Version ハンドシェイクでデバイスが返す自己情報。"""

    code: int | None = Field(description="プロトコル版", examples=[10])
    model: str | None = Field(description="機種名", examples=["Aladdin 2"])
    device_name: str | None = Field(description="デバイス名")
    pid: str | None = Field(description="機体 ID")
    aladdin_id: str | None = Field(description="Aladdin アカウント連携 ID")
    platform: str | None = Field(description="OS 系統", examples=["Android", "webos"])
    os_version: str | None = Field(description="OS 版")
    sdk_int: int | None = Field(description="Android API level")
    lang: str | None = Field(description="言語")
    country: str | None = Field(description="国")
    total_space: int | None = Field(description="ストレージ容量 (byte)")
    free_space: int | None = Field(description="ストレージ空き (byte)")
    server_access: bool | None = Field(description="クラウド接続の有無")
    feature_access: dict[str, int | None] | None = Field(
        description="機能ごとの利用可否 (1 = 利用可)。キーは focus / input / memory_release など"
    )
    capability: dict[str, int | None] | None = Field(
        description="対応機能 (1 = 対応、null = 不明)。キーは screenshot / app_list"
    )


class AlbumFile(BaseModel):
    name: str | None = Field(description="ファイル名")
    size: int | None = Field(description="byte")
    type: int | None = Field(description="1 = 写真, 2 = サムネイル, 10..12 = 時計")


class RemoteAlbum(BaseModel):
    """フォトメモリー (デバイス内アルバム) の状態。"""

    count: int | None = Field(description="保存されている写真の数")
    total_space: int | None = Field(description="byte")
    free_space: int | None = Field(description="byte")
    light_version: str | None = Field(description="ライト部のファームウェア版")
    files: list[AlbumFile] = Field(description="保存されているファイル")


class RemoteAppInfo(BaseModel):
    """デバイス上のアプリの有無と版。"""

    package: str | None = Field(description="package 名", examples=["jp.co.tver.tvapp"])
    installed: bool | None = Field(description="インストール済みか")
    version_code: int | None = Field(description="versionCode")
    version_name: str | None = Field(description="versionName")


class RemoteDeviceInfo(BaseModel):
    """UDP 制御チャネルの deviceInfo 応答 (action 30410)。前面アプリなど実行時の情報。"""

    device_name: str | None = Field(description="デバイス名")
    device_mode: str | None = Field(description="デバイスのモード")
    foreground_app: str | None = Field(description="前面アプリ名")
    foreground_package: str | None = Field(description="前面アプリの package")
    runtime: int | None = Field(description="稼働時間 (デバイス報告値、単位不明)")
    rom: int | None = Field(description="ROM 容量 (デバイス報告値)")
    mst: str | None = Field(description="デバイス報告値 (用途不明)")
    tips: str | None = Field(description="デバイス報告値 (用途不明)")


class DiscoveredDevice(BaseModel):
    """UDP 8100 ブロードキャストに応答した Aladdin。"""

    ip_address: str | None = Field(description="IP アドレス")
    model: str | None = Field(description="機種名", examples=["Aladdin 2"])
    name: str | None = Field(description="デバイス名")
    pid: str | None = Field(description="機体 ID")
    mac: str | None = Field(description="MAC アドレス")
    version: int | None = Field(description="プロトコル版")
    zipcode: str | None = Field(description="設定されている郵便番号")
    connected: bool | None = Field(description="他のクライアントが接続中か")
