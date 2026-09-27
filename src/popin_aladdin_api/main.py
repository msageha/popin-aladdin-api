"""FastAPI アプリ。デバイスクライアントの生成 / 破棄と、device 層の例外から HTTP status への変換を行う。"""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from importlib.metadata import version

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .api import router
from .device.errors import AladdinConnectionError, AladdinError
from .device.remote import RemoteClient
from .device.renderer import RendererClient
from .settings import settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    async with RendererClient(
        settings.hostname,
        port=settings.upnp_port,
        description_path=settings.description_path,
        timeout=settings.timeout,
    ) as renderer:
        app.state.renderer = renderer
        app.state.remote = RemoteClient(
            settings.hostname,
            tcp_port=settings.control_tcp_port,
            udp_port=settings.control_udp_port,
            timeout=settings.timeout,
        )
        app.state.device_lock = asyncio.Lock()
        yield


app = FastAPI(
    title="popIn Aladdin API",
    version=version("popin-aladdin-api"),
    description=(
        "popIn Aladdin をローカル LAN から監視 / 操作する API。"
        "UPnP/DLNA MediaRenderer (再生・音量・キャスト) と"
        "独自制御プロトコル (ライト・リモコンキー・文字入力・音声) をラップする。"
    ),
    lifespan=lifespan,
)
app.include_router(router)


@app.exception_handler(AladdinConnectionError)
async def connection_error(_: Request, exc: AladdinConnectionError) -> JSONResponse:
    return JSONResponse(status_code=504, content={"detail": str(exc)})


@app.exception_handler(AladdinError)
async def device_error(_: Request, exc: AladdinError) -> JSONResponse:
    return JSONResponse(
        status_code=502,
        content={
            "detail": str(exc),
            "fault_code": exc.fault_code,
            "upnp_error_code": exc.upnp_error_code,
        },
    )


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    return {"name": "popin-aladdin-api", "docs": "/docs"}
