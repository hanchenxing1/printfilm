# -*- coding: utf-8 -*-
"""终态但 billing_status=frozen 的对账补偿测试。

正常路径下 _complete_task/_fail_task/_mark_cancelled 都会在置终态后立即
settle_task；若该步因 DB 故障等异常中断，任务会停在「终态 + frozen」：
冻结额不退、usage_events 悬空。reconcile_terminal_frozen_tasks 周期收敛。
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import UsageEvent
from app.services.billing.settlement import (
    TERMINAL_FROZEN_RECONCILE_GRACE_SEC,
    freeze_for_task,
    reconcile_terminal_frozen_tasks,
)

from tests.conftest import make_task, make_user


async def _frozen_task(db: AsyncSession, user, *, status: str = "succeeded", age_minutes: int = 5):
    """freeze 后手工置终态（模拟置终态后 settle 失败的遗留行）。"""
    task = await make_task(db, user, domain="drama", task_type="fragment_video", status=status)
    await db.commit()
    need = await freeze_for_task(db, task)
    assert need > 0
    task.status = status
    task.finished_at = datetime.now(UTC) - timedelta(minutes=age_minutes)
    await db.commit()
    return task, need


@pytest.mark.asyncio
async def test_reconcile_settles_succeeded_frozen_after_grace(db_session: AsyncSession) -> None:
    """超过宽限期的 succeeded+frozen：按已落账用量结算并退差额。"""
    user = await make_user(db_session, balance_fen=100_000)
    task, need = await _frozen_task(db_session, user)
    charge = max(1, need - 200)
    db_session.add(
        UsageEvent(
            user_id=user.id,
            task_run_id=task.id,
            billing_key="drama_fragment_video",
            domain="drama",
            capability="video",
            provider="ark",
            charge_fen=charge,
            cost_fen=charge,
            settled=False,
        )
    )
    await db_session.commit()

    fixed = await reconcile_terminal_frozen_tasks(db_session)
    assert fixed == 1
    await db_session.commit()

    from app.models import User

    row = await db_session.get(type(task), int(task.id))
    owner = await db_session.get(User, int(user.id))
    assert row.billing_status == "settled"
    assert row.billing_charged_fen == charge
    assert row.billing_refunded_fen == need - charge
    assert owner.frozen_fen == 0
    assert owner.balance_fen == 100_000 - charge


@pytest.mark.asyncio
async def test_reconcile_skips_tasks_inside_grace_window(db_session: AsyncSession) -> None:
    """宽限期内的终态 frozen（可能正在正常收尾）不动。"""
    user = await make_user(db_session, balance_fen=100_000)
    task, need = await _frozen_task(db_session, user, age_minutes=0)
    # 刚结束：越过宽限截止线之前
    task.finished_at = datetime.now(UTC) - timedelta(
        seconds=max(0, TERMINAL_FROZEN_RECONCILE_GRACE_SEC - 30)
    )
    await db_session.commit()

    fixed = await reconcile_terminal_frozen_tasks(db_session)
    assert fixed == 0
    await db_session.refresh(task)
    assert task.billing_status == "frozen"
    assert user.frozen_fen == need


@pytest.mark.asyncio
async def test_reconcile_ignores_non_terminal_and_settled(db_session: AsyncSession) -> None:
    """进行中任务（awaiting_poll）与已结算终态都不应被扫描。"""
    user = await make_user(db_session, balance_fen=100_000)
    polling, _ = await _frozen_task(db_session, user, status="awaiting_poll")
    settled, _ = await _frozen_task(db_session, user, status="succeeded")
    settled.billing_status = "settled"
    await db_session.commit()

    fixed = await reconcile_terminal_frozen_tasks(db_session)
    assert fixed == 0
    await db_session.refresh(polling)
    assert polling.billing_status == "frozen"
    assert polling.status == "awaiting_poll"


@pytest.mark.asyncio
async def test_reconcile_full_refund_when_no_usage(db_session: AsyncSession) -> None:
    """终态 frozen 且无用量（如失败任务）：全额退回冻结。"""
    user = await make_user(db_session, balance_fen=100_000)
    task, need = await _frozen_task(db_session, user, status="failed")

    fixed = await reconcile_terminal_frozen_tasks(db_session)
    assert fixed == 1
    await db_session.commit()

    from app.models import User

    row = await db_session.get(type(task), int(task.id))
    owner = await db_session.get(User, int(user.id))
    assert row.billing_status == "settled"
    assert row.billing_charged_fen == 0
    assert row.billing_refunded_fen == need
    assert owner.frozen_fen == 0
    assert owner.balance_fen == 100_000
