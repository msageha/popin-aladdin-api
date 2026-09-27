from fastapi import APIRouter

from . import remote, renderer, system

router = APIRouter(prefix="/api")
router.include_router(system.router)
router.include_router(renderer.router)
router.include_router(remote.router)
