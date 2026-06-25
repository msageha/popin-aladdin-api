import asyncio
from collections.abc import Callable
from typing import Any, TypeVar

from aladdin import AladdinClient, AladdinRemoteClient
from config import Settings

T = TypeVar("T")


class AladdinService:
    def __init__(self, settings: Settings) -> None:
        self.client = AladdinClient(
            settings.popin_aladdin_host,
            upnp_port=settings.upnp_port,
            description_path=settings.description_path,
            timeout=settings.timeout,
        )
        self.remote = AladdinRemoteClient(
            settings.popin_aladdin_host,
            tcp_port=settings.control_tcp_port,
            udp_port=settings.control_udp_port,
            timeout=settings.timeout,
        )
        self._lock = asyncio.Lock()

    async def run(self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        async with self._lock:
            return await asyncio.to_thread(fn, *args, **kwargs)
