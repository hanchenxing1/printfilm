# -*- coding: utf-8 -*-
"""注册专属额度池（grant pool）。

独立于 balance 的第二池：注册赠送额度进 grant_fen，消费时优先扣，
grant_expire_at 到期后未用部分清零（由 scheduler 定期 + 惰性双触发）。
账本仍走 WalletLedger：grant 池行用 ref_type='grant'（池名）+ kind 区分，
balance 行保持 ref_type='task_run' 等原值，互不污染。
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, WalletLedger

logger = logging.getLogger(__name__)


def now_utc() -> datetime:
    return datetime.now(UTC)


def grant_expired(user: User) -> bool:
    """grant 池是否已到期（None 表示无限期/未设，永不到期）。"""
    exp = getattr(user, "grant_expire_at", None)
    if exp is None:
        return False
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=UTC)
    return exp <= now_utc()


def active_grant_fen(user: User) -> int:
    """当前可使用的专属额度（分）；池不存在或已到期均为 0。"""
    if grant_expired(user):
        return 0
    return max(0, int(getattr(user, "grant_fen", 0) or 0))


def grant_take(user: User, need: int) -> tuple[int, int]:
    """把 need 拆成 (专属池取用, balance 补足)；专属池优先。"""
    take_grant = min(max(0, int(need)), active_grant_fen(user))
    return take_grant, max(0, int(need) - take_grant)


def expire_user_grant(db: AsyncSession, user: User) -> int:
    """惰性清零：grant 池到期后把可用部分归零并记账；冻结中金额留给结算时释放。

    返回清零的可用分。未到期或无可清零时返回 0。"""
    if not grant_expired(user):
        return 0
    remain = max(0, int(getattr(user, "grant_fen", 0) or 0))
    user.grant_fen = 0
    if remain <= 0:
        return 0
    db.add(
        WalletLedger(
            user_id=int(user.id),
            delta_fen=-remain,
            balance_after=0,
            kind="grant_expired",
            ref_type="grant",
            ref_id=str(user.id),
            note=f"signup_grant_expired(cleared={remain})",
        )
    )
    logger.info("grant expired user=%s cleared=%s", user.id, remain)
    return remain


async def expire_expired_grants(db: AsyncSession, *, limit: int = 200) -> int:
    """批量清零到期的注册专属额度（scheduler 定期触发）。返回处理的用户数。"""
    stmt = select(User).where(
        User.grant_expire_at.is_not(None),
        User.grant_expire_at <= now_utc(),
    ).limit(limit)
    rows = list((await db.execute(stmt)).scalars().all())
    cleared_users = 0
    for user in rows:
        if expire_user_grant(db, user) > 0:
            cleared_users += 1
    if rows:
        await db.commit()
    return cleared_users
