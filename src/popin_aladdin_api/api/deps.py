from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Request

from ..device.remote import RemoteClient
from ..device.renderer import RendererClient


async def serialize_device_access(request: Request) -> AsyncGenerator[None]:
    """デバイスに触るリクエストを 1 つずつ処理する。

    複数 SOAP 呼び出しから成る操作 (cast, status) の途中に別リクエストが割り込むのを防ぎ、
    D-pad の押下 → 離上列を崩さないための、プロセス内で唯一の直列化点。
    """
    async with request.app.state.device_lock:
        yield


# 既定の scope="request" だと応答の送信完了までロックを保持し、遅い HTTP client が
# 全デバイス操作を止めるので、ハンドラの終了時点で返す。
device_lock = Depends(serialize_device_access, scope="function")


def get_renderer(request: Request) -> RendererClient:
    return request.app.state.renderer


def get_remote(request: Request) -> RemoteClient:
    return request.app.state.remote


RendererDep = Annotated[RendererClient, Depends(get_renderer)]
RemoteDep = Annotated[RemoteClient, Depends(get_remote)]
