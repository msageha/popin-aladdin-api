from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query

from ..device.models import (
    DiscoveredDevice,
    LightButton,
    ProjectorKey,
    RemoteAlbum,
    RemoteAppInfo,
    RemoteDeviceInfo,
    RemoteVersion,
)
from ..device.remote import DPAD_KEY_CODES, FOCUS_KEY_CODES, HARDWARE_KEY_CODES
from .deps import RemoteDep, device_lock
from .schemas import (
    DeeplinkRequest,
    KeyRequest,
    LightRequest,
    PowerOffRequest,
    TextRequest,
)

router = APIRouter(tags=["remote"], dependencies=[device_lock])

# Android の package 名。パスの一部として受けるので、ドット区切りの識別子だけに限る。
PackageName = Annotated[
    str,
    Path(
        pattern=r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+$",
        description="Android の package 名",
        examples=["jp.co.tver.tvapp"],
    ),
]


@router.get("/remote/buttons")
async def remote_buttons() -> dict[str, list[str]]:
    """利用できるボタン名を種類別に返す。デバイスには触れない。"""
    return {
        "light": list(LightButton),
        "key": [*DPAD_KEY_CODES, *FOCUS_KEY_CODES, ProjectorKey.HOME_LONG],
        "key_stateless": list(HARDWARE_KEY_CODES),
    }


@router.post("/remote/ping")
async def remote_ping(remote: RemoteDep) -> dict[str, bool]:
    await remote.ping()
    return {"ok": True}


@router.get("/remote/version")
async def remote_version(remote: RemoteDep) -> RemoteVersion:
    """Version ハンドシェイクで得る機種・OS・ストレージ・機能一覧。"""
    return await remote.version()


@router.get("/remote/album")
async def remote_album(remote: RemoteDep) -> RemoteAlbum:
    """フォトメモリーの枚数・容量と、ライト部のファームウェア版。"""
    return await remote.album()


@router.get("/remote/apps/{package}")
async def remote_app_info(package: PackageName, remote: RemoteDep) -> RemoteAppInfo:
    """アプリがインストールされているかと、その版。"""
    return await remote.app_info(package)


@router.get("/remote/device")
async def remote_device(remote: RemoteDep) -> RemoteDeviceInfo:
    """前面アプリなど、UDP 制御チャネルが返す実行時の情報。"""
    return await remote.device_info()


@router.get("/discover")
async def discover(
    remote: RemoteDep,
    wait: Annotated[float, Query(ge=0.5, le=15, description="応答を待つ秒数")] = 3.0,
) -> list[DiscoveredDevice]:
    """LAN にブロードキャストして Aladdin を探す。設定した接続先には依存しない。"""
    return await remote.discover(wait)


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


@router.post("/deeplink")
async def deeplink(body: DeeplinkRequest, remote: RemoteDep) -> DeeplinkRequest:
    """deeplink をデバイスで開く (アプリ起動)。"""
    await remote.open_deeplink(body.url)
    return body


@router.post("/memory/free")
async def free_memory(remote: RemoteDep) -> dict[str, str]:
    await remote.free_memory()
    return {"action": "free_memory"}


@router.post("/capture")
async def capture(remote: RemoteDep) -> dict[str, str]:
    """画面を撮影させ、デバイス上の画像 URL を返す。URL はデバイスと同じ LAN から取得できる。"""
    return {"action": "capture", "image_url": await remote.screenshot()}


@router.post("/power/off")
async def power_off(body: PowerOffRequest, remote: RemoteDep) -> dict[str, str]:
    """電源を切る。切った後はこの API から再点灯できないので confirm が必要。"""
    if not body.confirm:
        raise HTTPException(
            status_code=400, detail="set confirm=true to power off the device"
        )
    await remote.power_off()
    return {"action": "power_off"}
