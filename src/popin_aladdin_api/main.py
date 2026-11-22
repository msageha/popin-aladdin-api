"""FastAPI アプリ。デバイスクライアントの生成 / 破棄と、device 層の例外から HTTP status への変換を行う。"""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from importlib.metadata import version

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from popin_aladdin_api.api import router
from popin_aladdin_api.device.errors import AladdinConnectionError, AladdinError
from popin_aladdin_api.device.remote import RemoteClient
from popin_aladdin_api.device.renderer import RendererClient
from popin_aladdin_api.settings import settings


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
            cmd_udp_port=settings.control_cmd_udp_port,
            reply_udp_port=settings.control_reply_udp_port,
            discovery_udp_port=settings.discovery_udp_port,
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
        "独自制御プロトコル (ライト・リモコンキー・文字入力・音声・deeplink・デバイス情報・スクリーンショット) をラップする。"
    ),
    lifespan=lifespan,
)
app.include_router(router)


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    # 既定の応答は各エラーに入力値を付けるが、NaN や孤立した surrogate のように JSON の応答に
    # 書けない値では応答の生成が失敗して 500 になるので除く。
    errors = [
        {key: value for key, value in error.items() if key != "input"}
        for error in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(errors)})


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
