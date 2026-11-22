"""環境変数から読む設定。import 時に検証し、不正なら起動前に失敗する。"""

from urllib.parse import urlsplit

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    popin_aladdin_host: str = Field(
        min_length=1,
        description="デバイスの URL またはホスト名 / IP。ポートは各 *_PORT で指定する",
    )
    upnp_port: int = Field(default=1481, description="UPnP/DLNA MediaRenderer のポート")
    description_path: str = Field(
        default="/", description="UPnP device description のパス"
    )
    control_tcp_port: int = Field(
        default=30913,
        description="独自プロトコル TCP (ライト・文字入力・音声・deeplink・照会)",
    )
    control_udp_port: int = Field(
        default=16735,
        description="独自プロトコル UDP (方向キー・ハードキー)",
    )
    control_cmd_udp_port: int = Field(
        default=16750,
        description="独自プロトコル UDP JSON コマンド (スクリーンショット・メモリ解放・実行時情報・電源断)",
    )
    control_reply_udp_port: int = Field(
        default=16751,
        description="UDP JSON コマンドの応答を受け取るこのサーバー側のポート",
    )
    discovery_udp_port: int = Field(
        default=8100,
        description="デバイス発見のブロードキャスト先ポート",
    )
    timeout: float = Field(
        default=10.0, description="デバイスへの各リクエストのタイムアウト (秒)"
    )

    @property
    def hostname(self) -> str:
        """``popin_aladdin_host`` から scheme とポートを除いたホスト名。"""
        return urlsplit(self.popin_aladdin_host).hostname or self.popin_aladdin_host


settings = Settings()
