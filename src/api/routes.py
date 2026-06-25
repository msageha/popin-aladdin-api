from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from aladdin import all_buttons

from .schemas import (
    CastRequest,
    DeviceInfo,
    KeyRequest,
    LightRequest,
    MediaInfo,
    MuteRequest,
    PlayModeRequest,
    PlayRequest,
    PositionInfo,
    SeekRequest,
    SoapRequest,
    Status,
    TextRequest,
    TransportInfo,
    VolumeRequest,
)
from .service import AladdinService

router = APIRouter(prefix="/api")

# SOAP actions the raw passthrough treats as read-only (no confirm required).
_READONLY_ACTIONS = frozenset(
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


def get_service(request: Request) -> AladdinService:
    return request.app.state.aladdin


@router.get("/health", tags=["system"])
async def health(service: AladdinService = Depends(get_service)) -> dict[str, Any]:
    return {"status": "ok", "host": service.client.host}


@router.get("/info", response_model=DeviceInfo, tags=["status"])
async def info(service: AladdinService = Depends(get_service)) -> DeviceInfo:
    raw = await service.run(service.client.device_info)
    return DeviceInfo.model_validate(raw)


@router.get("/status", response_model=Status, tags=["status"])
async def status(service: AladdinService = Depends(get_service)) -> Status:
    raw = await service.run(service.client.status)
    return Status.model_validate(raw)


@router.get("/transport", response_model=TransportInfo, tags=["status"])
async def transport(service: AladdinService = Depends(get_service)) -> TransportInfo:
    raw = await service.run(service.client.transport_info)
    return TransportInfo.model_validate(raw)


@router.get("/position", response_model=PositionInfo, tags=["status"])
async def position(service: AladdinService = Depends(get_service)) -> PositionInfo:
    raw = await service.run(service.client.position_info)
    return PositionInfo.model_validate(raw)


@router.get("/media", response_model=MediaInfo, tags=["status"])
async def media(service: AladdinService = Depends(get_service)) -> MediaInfo:
    raw = await service.run(service.client.media_info)
    return MediaInfo.model_validate(raw)


@router.get("/protocol-info", tags=["status"])
async def protocol_info(
    service: AladdinService = Depends(get_service),
) -> dict[str, list[str]]:
    return await service.run(service.client.protocol_info)


@router.get("/volume", tags=["control"])
async def get_volume(
    service: AladdinService = Depends(get_service),
) -> dict[str, int | None]:
    return {"volume": await service.run(service.client.get_volume)}


@router.post("/volume", tags=["control"])
async def set_volume(
    body: VolumeRequest, service: AladdinService = Depends(get_service)
) -> dict[str, int]:
    await service.run(service.client.set_volume, body.volume)
    return {"volume": body.volume}


@router.get("/mute", tags=["control"])
async def get_mute(
    service: AladdinService = Depends(get_service),
) -> dict[str, bool | None]:
    return {"mute": await service.run(service.client.get_mute)}


@router.post("/mute", tags=["control"])
async def set_mute(
    body: MuteRequest, service: AladdinService = Depends(get_service)
) -> dict[str, bool]:
    await service.run(service.client.set_mute, body.mute)
    return {"mute": body.mute}


@router.post("/play", tags=["control"])
async def play(
    body: PlayRequest | None = None, service: AladdinService = Depends(get_service)
) -> dict[str, str]:
    speed = body.speed if body else "1"
    await service.run(service.client.play, speed)
    return {"action": "play", "speed": speed}


@router.post("/pause", tags=["control"])
async def pause(service: AladdinService = Depends(get_service)) -> dict[str, str]:
    await service.run(service.client.pause)
    return {"action": "pause"}


@router.post("/stop", tags=["control"])
async def stop(service: AladdinService = Depends(get_service)) -> dict[str, str]:
    await service.run(service.client.stop)
    return {"action": "stop"}


@router.post("/next", tags=["control"])
async def next_track(service: AladdinService = Depends(get_service)) -> dict[str, str]:
    await service.run(service.client.next)
    return {"action": "next"}


@router.post("/previous", tags=["control"])
async def previous_track(
    service: AladdinService = Depends(get_service),
) -> dict[str, str]:
    await service.run(service.client.previous)
    return {"action": "previous"}


@router.post("/seek", tags=["control"])
async def seek(
    body: SeekRequest, service: AladdinService = Depends(get_service)
) -> dict[str, float]:
    await service.run(service.client.seek, body.seconds)
    return {"seconds": body.seconds}


@router.post("/play-mode", tags=["control"])
async def play_mode(
    body: PlayModeRequest, service: AladdinService = Depends(get_service)
) -> dict[str, str]:
    await service.run(service.client.set_play_mode, body.mode)
    return {"play_mode": body.mode}


@router.post("/cast", tags=["control"])
async def cast(
    body: CastRequest, service: AladdinService = Depends(get_service)
) -> dict[str, Any]:
    await service.run(
        service.client.set_av_transport_uri,
        body.uri,
        metadata=body.metadata,
        title=body.title,
        upnp_class=body.upnp_class,
        autoplay=body.autoplay,
    )
    return {"uri": body.uri, "autoplay": body.autoplay}


@router.get("/remote/buttons", tags=["remote"])
async def remote_buttons() -> dict[str, list[str]]:
    return all_buttons()


@router.post("/remote/ping", tags=["remote"])
async def remote_ping(
    service: AladdinService = Depends(get_service),
) -> dict[str, bool]:
    return {"ok": await service.run(service.remote.ping)}


@router.post("/light", tags=["remote"])
async def light(
    body: LightRequest, service: AladdinService = Depends(get_service)
) -> dict[str, Any]:
    for _ in range(body.repeat):
        await service.run(service.remote.light, body.button)
    return {"button": body.button, "repeat": body.repeat}


@router.post("/key", tags=["remote"])
async def key(
    body: KeyRequest, service: AladdinService = Depends(get_service)
) -> dict[str, Any]:
    for _ in range(body.repeat):
        await service.run(service.remote.key, body.button)
    return {"button": body.button, "repeat": body.repeat}


@router.post("/keyboard", tags=["remote"])
async def keyboard(
    body: TextRequest, service: AladdinService = Depends(get_service)
) -> dict[str, str]:
    await service.run(service.remote.text, body.text)
    return {"text": body.text}


@router.post("/voice", tags=["remote"])
async def voice(
    body: TextRequest, service: AladdinService = Depends(get_service)
) -> dict[str, str]:
    await service.run(service.remote.voice_control, body.text)
    return {"text": body.text}


@router.post("/memory/free", tags=["remote"])
async def free_memory(
    service: AladdinService = Depends(get_service),
) -> dict[str, str]:
    await service.run(service.remote.free_memory)
    return {"action": "free_memory"}


@router.post("/capture", tags=["remote"])
async def capture(
    service: AladdinService = Depends(get_service),
) -> dict[str, str]:
    await service.run(service.remote.capture)
    return {"action": "capture"}


@router.post("/soap", tags=["raw"])
async def soap(
    body: SoapRequest, service: AladdinService = Depends(get_service)
) -> dict[str, Any]:
    if body.action not in _READONLY_ACTIONS and not body.confirm:
        raise HTTPException(
            status_code=400,
            detail=f"Set confirm=true to send the control action {body.action!r}",
        )
    result = await service.run(
        service.client.invoke, body.service, body.action, body.args
    )
    return {
        "service": body.service,
        "action": body.action,
        "result": result,
    }
