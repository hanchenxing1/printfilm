"""用户自加的 Agnes API Key（加密入库 + 作用域注入）。

本地部署模式下，用户可在「个人中心 / API」添加自己的 Agnes Key，
后续该用户触发的 Agnes 视频生成优先用其自加 key（回退全局池）。
"""

from __future__ import annotations

import base64
import hashlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.models_api import UserAgnesKey

logger = logging.getLogger(__name__)

ENC_PREFIX = "enc:"
_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        from app.config import get_settings

        digest = hashlib.sha256(get_settings().secret_key.encode("utf-8")).digest()
        _fernet = Fernet(base64.urlsafe_b64encode(digest))
    return _fernet


def _encrypt(value: str) -> str:
    return ENC_PREFIX + _get_fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def _decrypt(value: str) -> str:
    if not value:
        return ""
    if not value.startswith(ENC_PREFIX):
        return value
    try:
        return _get_fernet().decrypt(value[len(ENC_PREFIX):].encode("utf-8")).decode("utf-8")
    except InvalidToken:
        logger.warning("Agnes key 无法用当前 SECRET_KEY 解密，已忽略（需重填）")
        return ""


def active_user_agnes_keys() -> tuple[str, ...] | None:
    from app.services import agnes_client

    return agnes_client.active_user_agnes_keys()


@asynccontextmanager
async def user_agnes_scope(
    db: AsyncSession, user: User | None
) -> AsyncIterator[tuple[str, ...] | None]:
    """把 user 的 Agnes key 池设为当前生效，exit 时还原。未配置则回退全局池。"""
    from app.services import agnes_client

    if user is None:
        yield None
        return
    keys = await active_agnes_keys(db, user.id)
    token = agnes_client.set_user_agnes_keys(tuple(keys) if keys else None)
    try:
        yield tuple(keys) if keys else None
    finally:
        agnes_client.reset_user_agnes_keys(token)


def _short_prefix(key: str) -> str:
    s = key.strip()
    return (s[:4] + "…" + s[-2:]) if len(s) > 10 else s[:6]


async def add_agnes_key(
    db: AsyncSession, user: User, name: str, raw_key: str
) -> UserAgnesKey:
    raw_key = raw_key.strip()
    if not raw_key:
        raise ValueError("Agnes key 不能为空")
    row = UserAgnesKey(
        user_id=user.id,
        name=(name or "默认 Agnes Key").strip()[:64] or "默认 Agnes Key",
        key_prefix=_short_prefix(raw_key),
        key_enc=_encrypt(raw_key),
        active=True,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


async def list_agnes_keys(db: AsyncSession, user_id: int) -> list[UserAgnesKey]:
    rows = await db.execute(
        select(UserAgnesKey)
        .where(UserAgnesKey.user_id == user_id)
        .order_by(UserAgnesKey.id.asc())
    )
    return list(rows.scalars().all())


async def remove_agnes_key(db: AsyncSession, user_id: int, key_id: int) -> bool:
    row = await db.get(UserAgnesKey, key_id)
    if not row or row.user_id != user_id:
        return False
    await db.delete(row)
    await db.flush()
    return True


async def set_active(db: AsyncSession, user_id: int, key_id: int, active: bool) -> bool:
    row = await db.get(UserAgnesKey, key_id)
    if not row or row.user_id != user_id:
        return False
    row.active = bool(active)
    await db.flush()
    return True


async def active_agnes_keys(db: AsyncSession, user_id: int) -> list[str]:
    rows = await db.execute(
        select(UserAgnesKey).where(
            UserAgnesKey.user_id == user_id,
            UserAgnesKey.active.is_(True),
        )
    )
    out: list[str] = []
    for row in rows.scalars().all():
        k = _decrypt(row.key_enc)
        if k:
            out.append(k)
    return out


async def mark_used(db: AsyncSession, user_id: int, used_at: datetime | None = None) -> None:
    ts = used_at or datetime.now(timezone.utc)
    rows = await db.execute(
        select(UserAgnesKey).where(
            UserAgnesKey.user_id == user_id,
            UserAgnesKey.active.is_(True),
        )
    )
    for row in rows.scalars().all():
        row.last_used_at = ts
