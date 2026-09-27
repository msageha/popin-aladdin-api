from fastapi import APIRouter

from ..device.models import LightButton
from ..device.remote import DPAD_KEY_CODES, HARDWARE_KEY_CODES
from .deps import RemoteDep, device_lock
from .schemas import KeyRequest, LightRequest, TextRequest

router = APIRouter(tags=["remote"], dependencies=[device_lock])


@router.get("/remote/buttons")
async def remote_buttons() -> dict[str, list[str]]:
    """利用できるボタン名を種類別に返す。デバイスには触れない。"""
    return {
        "light": list(LightButton),
        "key": list(DPAD_KEY_CODES),
        "key_stateless": list(HARDWARE_KEY_CODES),
    }


@router.post("/remote/ping")
async def remote_ping(remote: RemoteDep) -> dict[str, bool]:
    await remote.ping()
    return {"ok": True}


@router.post("/light")
async def light(body: LightRequest, remote: RemoteDep) -> LightRequest:
    for _ in range(body.repeat):
        await remote.light(body.button)
    return body


@router.post("/key")
async def key(body: KeyRequest, remote: RemoteDep) -> KeyRequest:
    for _ in range(body.repeat):
        await remote.press_key(body.button)
    return body


@router.post("/keyboard")
async def keyboard(body: TextRequest, remote: RemoteDep) -> TextRequest:
    await remote.type_text(body.text)
    return body


@router.post("/voice")
async def voice(body: TextRequest, remote: RemoteDep) -> TextRequest:
    await remote.voice_command(body.text)
    return body


@router.post("/memory/free")
async def free_memory(remote: RemoteDep) -> dict[str, str]:
    await remote.free_memory()
    return {"action": "free_memory"}


@router.post("/capture")
async def capture(remote: RemoteDep) -> dict[str, str]:
    await remote.capture()
    return {"action": "capture"}
