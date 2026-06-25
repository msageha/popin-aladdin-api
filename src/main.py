from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from aladdin import AladdinConnectionError, AladdinError
from api import router
from api.service import AladdinService
from config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.aladdin = AladdinService(settings)
    yield


app = FastAPI(
    title="popIn Aladdin API",
    version="0.1.0",
    description=(
        "Local monitoring/control API for the popIn Aladdin, wrapping its "
        "UPnP/DLNA MediaRenderer (AVTransport + RenderingControl)."
    ),
    lifespan=lifespan,
)
app.include_router(router)


@app.exception_handler(AladdinConnectionError)
async def _conn_handler(_: Request, exc: AladdinConnectionError) -> JSONResponse:
    return JSONResponse(status_code=504, content={"detail": exc.message})


@app.exception_handler(AladdinError)
async def _aladdin_handler(_: Request, exc: AladdinError) -> JSONResponse:
    return JSONResponse(
        status_code=502,
        content={
            "detail": exc.message,
            "fault_code": exc.fault_code,
            "upnp_error_code": exc.upnp_error_code,
        },
    )


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    return {"name": "popin-aladdin-api", "docs": "/docs"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
