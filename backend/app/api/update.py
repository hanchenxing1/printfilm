# -*- coding: utf-8 -*-
"""客户端在线更新接口（公开只读）。

GET /api/update/check?platform=desktop&current_version=1.0.0
    返回该平台最新版本条目，并给出 update_available / version 供客户端判断是否弹窗。
    无需登录——双端壳在启动/轮询时直接调用，未登录也能提示更新。
"""
from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.services import update_releases

router = APIRouter(prefix="/update", tags=["update"])


class UpdateCheckOut(BaseModel):
    platform: str
    update_available: bool
    force: bool
    has_release: bool
    # 当前版本（回显入参）
    current_version: str | None
    # 服务端最新版本；无条目时为空串
    latest_version: str
    url: str
    notes: str
    version_code: int | None
    size: int | None
    published_at: str | None


@router.get("/check", response_model=UpdateCheckOut)
async def update_check(
    platform: str = Query("desktop", pattern="^(desktop|mobile)$"),
    current_version: str | None = Query(default=None),
) -> dict:
    entry = update_releases.get_latest(platform)
    latest = str(entry.get("version") or "")
    cur = (current_version or "").strip()

    if not entry:
        return {
            "platform": platform,
            "update_available": False,
            "force": False,
            "has_release": False,
            "current_version": cur or None,
            "latest_version": "",
            "url": "",
            "notes": "",
            "version_code": None,
            "size": None,
            "published_at": None,
        }

    available = bool(cur) and update_releases.is_newer(latest, cur)
    return {
        "platform": platform,
        "update_available": available,
        "force": bool(entry.get("force")),
        "has_release": True,
        "current_version": cur or None,
        "latest_version": latest,
        "url": entry.get("url") or "",
        "notes": entry.get("notes") or "",
        "version_code": entry.get("version_code"),
        "size": entry.get("size"),
        "published_at": entry.get("published_at"),
    }
