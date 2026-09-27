from typing import Any

from fastapi import APIRouter, HTTPException

from ..device.models import (
    DeviceInfo,
    MediaInfo,
    PositionInfo,
    ProtocolInfo,
    RendererStatus,
    TransportInfo,
)
from .deps import RendererDep, device_lock
from .schemas import (
    CastRequest,
    Mute,
    PlayModeRequest,
    PlayRequest,
    SeekRequest,
    SoapRequest,
    Volume,
)

router = APIRouter(dependencies=[device_lock])

# /soap で confirm 無しに送れる、状態を変えないと分かっている標準アクション。
READONLY_SOAP_ACTIONS = frozenset(
    {
        "GetTransportInfo",
        "GetPositionInfo",
        "GetMediaInfo",
        "GetTransportSettings",
        "GetCurrentTransportActions",
        "GetDeviceCapabilities",
        "GetVolume",
        "GetVolumeDB",
        "GetVolumeDBRange",
        "GetMute",
        "ListPresets",
        "GetProtocolInfo",
        "GetCurrentConnectionIDs",
        "GetCurrentConnectionInfo",
    }
)


@router.get("/info", tags=["status"])
async def info(renderer: RendererDep) -> DeviceInfo:
    return await renderer.device_info()


@router.get("/status", tags=["status"])
async def status(renderer: RendererDep) -> RendererStatus:
    return await renderer.status()


@router.get("/transport", tags=["status"])
async def transport(renderer: RendererDep) -> TransportInfo:
    return await renderer.transport_info()


@router.get("/position", tags=["status"])
async def position(renderer: RendererDep) -> PositionInfo:
    return await renderer.position_info()


@router.get("/media", tags=["status"])
async def media(renderer: RendererDep) -> MediaInfo:
    return await renderer.media_info()


@router.get("/protocol-info", tags=["status"])
async def protocol_info(renderer: RendererDep) -> ProtocolInfo:
    return await renderer.protocol_info()


@router.get("/volume", tags=["control"])
async def get_volume(renderer: RendererDep) -> Volume:
    return Volume(volume=await renderer.get_volume())


@router.post("/volume", tags=["control"])
async def set_volume(body: Volume, renderer: RendererDep) -> Volume:
    await renderer.set_volume(body.volume)
    return body


@router.get("/mute", tags=["control"])
async def get_mute(renderer: RendererDep) -> Mute:
    return Mute(mute=await renderer.get_mute())


@router.post("/mute", tags=["control"])
async def set_mute(body: Mute, renderer: RendererDep) -> Mute:
    await renderer.set_mute(body.mute)
    return body


@router.post("/play", tags=["control"])
async def play(
    renderer: RendererDep, body: PlayRequest | None = None
) -> dict[str, str]:
    body = body or PlayRequest()
    await renderer.play(body.speed)
    return {"action": "play", "speed": body.speed}


@router.post("/pause", tags=["control"])
async def pause(renderer: RendererDep) -> dict[str, str]:
    await renderer.pause()
    return {"action": "pause"}


@router.post("/stop", tags=["control"])
async def stop(renderer: RendererDep) -> dict[str, str]:
    await renderer.stop()
    return {"action": "stop"}


@router.post("/next", tags=["control"])
async def next_track(renderer: RendererDep) -> dict[str, str]:
    await renderer.next()
    return {"action": "next"}


@router.post("/previous", tags=["control"])
async def previous_track(renderer: RendererDep) -> dict[str, str]:
    await renderer.previous()
    return {"action": "previous"}


@router.post("/seek", tags=["control"])
async def seek(body: SeekRequest, renderer: RendererDep) -> SeekRequest:
    await renderer.seek(body.seconds)
    return body


@router.post("/play-mode", tags=["control"])
async def play_mode(body: PlayModeRequest, renderer: RendererDep) -> dict[str, str]:
    await renderer.set_play_mode(body.mode)
    return {"play_mode": body.mode}


@router.post("/cast", tags=["control"])
async def cast(body: CastRequest, renderer: RendererDep) -> dict[str, Any]:
    await renderer.cast(
        body.uri,
        title=body.title,
        upnp_class=body.upnp_class,
        metadata=body.metadata,
        autoplay=body.autoplay,
    )
    return {"uri": body.uri, "autoplay": body.autoplay}


@router.post("/soap", tags=["raw"])
async def soap(body: SoapRequest, renderer: RendererDep) -> dict[str, Any]:
    """任意の SOAP アクションを送るパススルー。状態を変えうるアクションは confirm が必要。"""
    if body.action not in READONLY_SOAP_ACTIONS and not body.confirm:
        raise HTTPException(
            status_code=400,
            detail=f"set confirm=true to send the control action {body.action!r}",
        )
    result = await renderer.invoke(body.service, body.action, body.args)
    return {"service": body.service, "action": body.action, "result": result}
