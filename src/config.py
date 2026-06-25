from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Maps to POPIN_ALADDIN_HOST in .env (e.g. http://172.16.1.113).
    popin_aladdin_host: str = "http://172.16.1.113"

    # The popIn Aladdin exposes its UPnP/DLNA MediaRenderer ("Aladdin 2") on
    # this port; the device description document lives at description_path.
    upnp_port: int = 1481
    description_path: str = "/"

    # Proprietary "popIn"/MAXHUB control protocol: ceiling light + text/voice
    # over TCP, projector D-pad / hardware keys over UDP.
    control_tcp_port: int = 30913
    control_udp_port: int = 16735

    # USERNAME / PASSWORD are read from .env for completeness only. The local
    # UPnP/DLNA renderer requires no authentication, so they are unused.
    username: str | None = None
    password: str | None = None

    timeout: int = 10


@lru_cache
def get_settings() -> Settings:
    # All fields have defaults; pydantic-settings overrides them from the
    # environment / .env at runtime.
    return Settings()
