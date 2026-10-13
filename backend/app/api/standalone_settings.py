# -*- coding: utf-8 -*-
"""Standalone settings endpoints: Agnes API key management + local key status.

挂在 /api/settings/*（非 admin），单机版免登录直接可用。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.services import agnes_key_store

router = APIRouter(prefix="/settings", tags=["standalone-settings"])


class AgnesKeyIn(BaseModel):
    keys: list[str]


@router.get("/agnes-keys")
async def get_agnes_keys(
    _user: User = Depends(get_current_user),
) -> dict:
    """当前保存的 Agnes key 状态（脱敏）。"""
    return agnes_key_store.key_status()


@router.put("/agnes-keys")
async def put_agnes_keys(
    body: AgnesKeyIn,
    _user: User = Depends(get_current_user),
) -> dict:
    """保存/覆盖用户 Agnes key（可多个，逗号分隔或数组）。

    若 key 已存在于列表则跳过重复；保存后立即对 agnes_client 单例生效。
    """
    out = agnes_key_store.save_keys(body.keys)
    return {"ok": True, "count": len(out), **agnes_key_store.key_status()}


@router.delete("/agnes-keys")
async def delete_agnes_keys(
    _user: User = Depends(get_current_user),
) -> dict:
    """清空本地保存的 Agnes key。"""
    agnes_key_store.save_keys([])
    return {"ok": True, **agnes_key_store.key_status()}


@router.get("/health")
async def settings_health(_user=None) -> dict:
    """Agnes 引擎可用性（无需登录），供设置页 / 启动引导使用。"""
    from app.services import agnes_key_store

    try:
        from app.services import agnes_client

        client = agnes_client.get_agnes_client()
    except Exception:  # noqa: BLE001
        client = None
    keys = agnes_key_store.load_keys()
    return {
        "ok": True,
        "app": "PRINTFILM-Standalone",
        "agnes": {
            "configured": bool(client),
            "key_count": len(keys),
            "text_model": client.text_model if client else None,
            "image_model": client.image_model if client else None,
            "video_model": client.video_model if client else None,
            "base_url": client.base_url if client else None,
        },
    }


@router.get("/agnes-test")
async def test_agnes_key(
    key: str | None = None,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """校验一把（或默认池内任意）Agnes key 是否可用。

    只发一次最小 LLM 调用（agnes text 模型，1 token）确认连通。
    """
    from app.services import agnes_client

    target = (key or "").strip() or None
    client = agnes_client.get_agnes_client()
    if not client:
        return {"ok": False, "message": "没有可用的 Agnes key（请先到设置页填写）"}
    if target:
        client.api_keys = [target] + [k for k in client.api_keys if k != target]
    try:
        resp = await client.chat("Reply with the single word: ok", max_tokens=8)
        ok = bool(resp and resp.strip())
        return {
            "ok": ok,
            "message": "连接正常" if ok else "调用返回空",
            "model": client.text_model,
            "key_used": (target or (client.api_keys[0] if client.api_keys else ""))[:8] + "…",
        }
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "message": f"调用失败: {type(e).__name__}: {e}"}
