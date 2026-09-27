from fastapi import APIRouter

from ..settings import settings

router = APIRouter(tags=["system"])


@router.get("/health")
async def health() -> dict[str, str]:
    """デバイスには触れず、サーバーの生存と接続先だけを返す。"""
    return {"status": "ok", "host": settings.popin_aladdin_host}
