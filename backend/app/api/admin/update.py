# -*- coding: utf-8 -*-
"""客户端更新版本管理（admin）。

POST /api/admin/update/release  登记/更新某平台最新安装包（写 data/update_releases.json，
     双端下次启动检测时即弹出新版提示，无需重启后端）。
GET  /api/admin/update/releases 查看当前清单 + 历史。
"""
import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.deps import get_current_admin
from app.models import User
from app.services import update_releases

router = APIRouter()
logger = logging.getLogger(__name__)


class UpdateReleaseIn(BaseModel):
    platform: str = Field(pattern="^(desktop|mobile)$")
    version: str = Field(minLength=1)
    url: str = Field(minLength=1)
    notes: str = ""
    force: bool = False
    version_code: int | None = None
    size: int | None = None


@router.post("/release")
async def post_update_release(
    body: UpdateReleaseIn,
    admin: User = Depends(get_current_admin),
) -> dict:
    try:
        entry = update_releases.upsert_release(
            body.platform,
            version=body.version,
            url=body.url,
            notes=body.notes,
            force=body.force,
            version_code=body.version_code,
            size=body.size,
        )
    except ValueError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "platform": body.platform, "release": entry}


@router.get("/releases")
async def list_update_releases(
    admin: User = Depends(get_current_admin),
) -> dict:
    data = update_releases.all_releases()
    return {
        "desktop": data.get("desktop"),
        "mobile": data.get("mobile"),
        "history": data.get("history", [])[:20],
        "manifest_path": str(update_releases.MANIFEST_PATH),
    }
