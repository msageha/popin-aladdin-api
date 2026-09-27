"""環境変数 / ``.env`` から読む設定。import 時に検証し、不正なら起動前に失敗する。"""

from urllib.parse import urlsplit

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .device.remote import REMOTE_TCP_PORT, REMOTE_UDP_PORT
from .device.renderer import UPNP_PORT


class Settings(BaseSettings):
    # .env.example には未使用のキー (USERNAME / PASSWORD) が残っているため extra は無視する。
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    popin_aladdin_host: str = Field(
        default="http://172.16.1.113",
        description="デバイスの URL またはホスト名 / IP。ポートは各 *_PORT で指定する",
    )
    upnp_port: int = Field(
        default=UPNP_PORT, description="UPnP/DLNA MediaRenderer のポート"
    )
    description_path: str = Field(
        default="/", description="UPnP device description のパス"
    )
    control_tcp_port: int = Field(
        default=REMOTE_TCP_PORT,
        description="独自プロトコル TCP (ライト・文字入力・音声)",
    )
    control_udp_port: int = Field(
        default=REMOTE_UDP_PORT,
        description="独自プロトコル UDP (方向キー・ハードキー・保守)",
    )
    timeout: float = Field(
        default=10.0, description="デバイスへの各リクエストのタイムアウト (秒)"
    )

    @property
    def hostname(self) -> str:
        """``popin_aladdin_host`` から scheme とポートを除いたホスト名。"""
        return urlsplit(self.popin_aladdin_host).hostname or self.popin_aladdin_host


settings = Settings()
