# -*- coding: utf-8 -*-
"""finalizing 成片收尾窗口与取消竞态的回归测试。

场景：poller 已认领分镜视频、进入 finalizing 窗口（成片正在下载落盘）时，
scheduler/executor 侧的取消不得直接全额退款，否则：
  1. 随后落盘的 usage_events 永久 settled=False（悬空）；
  2. 冻结额被全额退回 → 钱货两失。
修复三层：service 窗口判定 helper / executor._mark_cancelled 窗口内让位 /
jobs._settle_cancelled_after_finalized 下载后按实结算。
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import UsageEvent, WalletLedger
from app.models_tasks import TaskEvent, TaskRun
from app.services.billing.settlement import freeze_for_task
from app.services.drama import jobs as drama_jobs
from app.services.tasks import executor
from app.services.tasks.service import (
    FINALIZING_UNTIL_KEY,
    clear_finalizing_window,
    task_finalizing_window_open,
)

from tests.conftest import make_task, make_user


def _task_ns(payload: object, *, status: str = "cancel_requested") -> SimpleNamespace:
    """构造 _mark_cancelled 所需的最小任务对象（steps 为空，避免懒加载）。"""
    return SimpleNamespace(
        id=11,
        payload=payload,
        status=status,
        steps=[],
        current_step_key="fragment_video",
        current_step_status="polling",
        finished_at=None,
        next_action_at=datetime.now(UTC),
        lease_until=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# 一、纯函数：窗口判定
# ---------------------------------------------------------------------------


def test_window_open_true_for_future_timestamp() -> None:
    task = SimpleNamespace(payload={FINALIZING_UNTIL_KEY: (datetime.now(UTC) + timedelta(minutes=5)).isoformat()})
    assert task_finalizing_window_open(task) is True


def test_window_closed_for_past_timestamp() -> None:
    task = SimpleNamespace(payload={FINALIZING_UNTIL_KEY: (datetime.now(UTC) - timedelta(minutes=5)).isoformat()})
    assert task_finalizing_window_open(task) is False


def test_window_naive_timestamp_treated_as_utc() -> None:
    # naive 时间按 UTC 解释：未来的 naive 时间戳在窗口内
    future_naive = datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=5)
    assert task_finalizing_window_open(SimpleNamespace(payload={FINALIZING_UNTIL_KEY: future_naive.isoformat()})) is True
    past_naive = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=5)
    assert task_finalizing_window_open(SimpleNamespace(payload={FINALIZING_UNTIL_KEY: past_naive.isoformat()})) is False


def test_window_closed_without_key_or_bad_payload() -> None:
    assert task_finalizing_window_open(SimpleNamespace(payload={})) is False
    assert task_finalizing_window_open(SimpleNamespace(payload=None)) is False
    assert task_finalizing_window_open(SimpleNamespace(payload="not-a-dict")) is False
    assert task_finalizing_window_open(SimpleNamespace(payload={FINALIZING_UNTIL_KEY: None})) is False
    assert task_finalizing_window_open(SimpleNamespace(payload={FINALIZING_UNTIL_KEY: "not-a-date"})) is False


def test_window_respects_injected_now() -> None:
    until = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)
    task = SimpleNamespace(payload={FINALIZING_UNTIL_KEY: until.isoformat()})
    assert task_finalizing_window_open(task, now=datetime(2026, 9, 14, 11, 59, tzinfo=UTC)) is True
    assert task_finalizing_window_open(task, now=datetime(2026, 9, 14, 12, 1, tzinfo=UTC)) is False


def test_clear_window_returns_copy_without_mutating_original() -> None:
    original = {FINALIZING_UNTIL_KEY: "2026-09-14T12:00:00+00:00", "episode_id": 7}
    cleared = clear_finalizing_window(original)
    assert FINALIZING_UNTIL_KEY not in cleared
    assert cleared["episode_id"] == 7
    # 原 dict 不被修改（不可变风格）
    assert FINALIZING_UNTIL_KEY in original


def test_clear_window_handles_missing_key_and_non_dict() -> None:
    assert clear_finalizing_window({"a": 1}) == {"a": 1}
    assert clear_finalizing_window(None) == {}
    assert clear_finalizing_window("x") == {}


# ---------------------------------------------------------------------------
# 二、executor._mark_cancelled：窗口内让位，窗口外收敛
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mark_cancelled_defers_inside_finalizing_window() -> None:
    task = _task_ns({FINALIZING_UNTIL_KEY: (datetime.now(UTC) + timedelta(minutes=5)).isoformat()})
    db = MagicMock()
    db.commit = AsyncMock()

    with (
        patch.object(executor, "settle_task", new=AsyncMock()) as settle_mock,
        patch.object(executor, "append_task_event", new=AsyncMock()) as event_mock,
    ):
        await executor._mark_cancelled(db, task)

    # 任务保持取消请求态：不结算、不记事件、不提交，等待收尾协程按实结算
    assert task.status == "cancel_requested"
    assert task.finished_at is None
    settle_mock.assert_not_awaited()
    event_mock.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_mark_cancelled_settles_after_window_expired() -> None:
    task = _task_ns(
        {FINALIZING_UNTIL_KEY: (datetime.now(UTC) - timedelta(minutes=11)).isoformat()},
        status="cancel_requested",
    )
    db = MagicMock()
    db.commit = AsyncMock()

    with (
        patch.object(executor, "settle_task", new=AsyncMock()) as settle_mock,
        patch.object(executor, "append_task_event", new=AsyncMock()) as event_mock,
    ):
        await executor._mark_cancelled(db, task)

    assert task.status == "cancelled"
    assert task.finished_at is not None
    assert task.next_action_at is None
    assert task.lease_until is None
    settle_mock.assert_awaited_once_with(db, task.id)
    event_mock.assert_awaited_once()
    db.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# 三、jobs._settle_cancelled_after_finalized：单元级字段收敛
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_settle_cancelled_after_finalized_returns_false_without_lock() -> None:
    db = MagicMock()
    db.commit = AsyncMock()
    with (
        patch("app.services.billing.settlement._lock_task", new=AsyncMock(return_value=None)),
        patch("app.services.billing.settlement.settle_task", new=AsyncMock()) as settle_mock,
    ):
        ok = await drama_jobs._settle_cancelled_after_finalized(db, 99)
    assert ok is False
    settle_mock.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_settle_cancelled_after_finalized_marks_done_and_clears_window() -> None:
    locked = SimpleNamespace(
        id=77,
        payload={FINALIZING_UNTIL_KEY: "2026-09-14T12:00:00+00:00", "episode_id": 3},
        status="awaiting_poll",
        cancel_requested=False,
        current_step_status="finalizing",
        progress_percent=90,
        finished_at=None,
        next_action_at=datetime.now(UTC),
        lease_token="tok",
        lease_until=datetime.now(UTC),
    )
    db = MagicMock()
    db.commit = AsyncMock()

    with (
        patch("app.services.billing.settlement._lock_task", new=AsyncMock(return_value=locked)),
        patch("app.services.billing.settlement.settle_task", new=AsyncMock()) as settle_mock,
        patch("app.services.tasks.service.append_task_event", new=AsyncMock()) as event_mock,
    ):
        ok = await drama_jobs._settle_cancelled_after_finalized(db, 77)

    assert ok is True
    assert locked.status == "cancelled"
    assert locked.cancel_requested is True
    assert locked.current_step_status == "done"
    assert locked.progress_percent == 100
    assert locked.finished_at is not None
    assert locked.next_action_at is None
    assert locked.lease_token is None
    assert locked.lease_until is None
    # 窗口键清除，其余 payload 保留
    assert FINALIZING_UNTIL_KEY not in locked.payload
    assert locked.payload["episode_id"] == 3
    settle_mock.assert_awaited_once_with(db, 77)
    event_mock.assert_awaited_once()
    db.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# 四、DB 集成：真实 freeze/settle，验证"按实结算、不退全款、账实相符"
# ---------------------------------------------------------------------------


async def _frozen_fragment_task(db: AsyncSession, user) -> tuple[TaskRun, int]:
    """造一个已预扣、处于 finalizing 窗口的分镜视频任务。"""
    task = await make_task(
        db,
        user,
        domain="drama",
        task_type="fragment_video",
        status="awaiting_poll",
    )
    task.payload = {FINALIZING_UNTIL_KEY: (datetime.now(UTC) + timedelta(minutes=10)).isoformat()}
    await db.commit()
    need = await freeze_for_task(db, task)
    assert need > 0
    await db.commit()
    return task, need


@pytest.mark.asyncio
async def test_finalized_cancel_settles_actual_usage_not_full_refund(db_session: AsyncSession) -> None:
    """窗口内取消、成片已落账：退差额而非全款，usage 行全部 settled。"""
    user = await make_user(db_session, balance_fen=100_000)
    task, need = await _frozen_fragment_task(db_session, user)
    # 成片下载后落入的真实用量（小于冻结额，应退 need-charge）
    charge = max(1, need - 100)
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

    ok = await drama_jobs._settle_cancelled_after_finalized(db_session, int(task.id))
    assert ok is True
    await db_session.commit()

    row = await db_session.get(TaskRun, int(task.id))
    assert row.status == "cancelled"
    assert row.billing_status == "settled"
    assert row.billing_charged_fen == charge
    assert row.billing_refunded_fen == need - charge
    assert FINALIZING_UNTIL_KEY not in (row.payload or {})
    # 钱包：冻结清零，余额 = 初始 - 实扣
    assert user.frozen_fen == 0
    assert user.balance_fen == 100_000 - charge

    events = list(
        (
            await db_session.execute(select(UsageEvent).where(UsageEvent.task_run_id == task.id))
        ).scalars()
    )
    assert events and all(e.settled for e in events)

    unfreeze = list(
        (
            await db_session.execute(
                select(WalletLedger).where(
                    WalletLedger.ref_type == "task_run",
                    WalletLedger.ref_id == str(task.id),
                    WalletLedger.kind == "unfreeze",
                )
            )
        ).scalars()
    )
    assert len(unfreeze) == 1
    assert unfreeze[0].delta_fen == need - charge

    task_events = list(
        (
            await db_session.execute(select(TaskEvent).where(TaskEvent.task_id == task.id))
        ).scalars()
    )
    assert any(e.event_type == "task.cancelled" for e in task_events)


@pytest.mark.asyncio
async def test_mark_cancelled_inside_window_keeps_freeze_intact(db_session: AsyncSession) -> None:
    """executor 窗口内让位：冻结额不动、无退款流水、任务仍 cancel_requested。"""
    user = await make_user(db_session, balance_fen=100_000)
    task, need = await _frozen_fragment_task(db_session, user)
    task.status = "cancel_requested"
    task.cancel_requested = True
    await db_session.commit()

    # selectinload steps，避免 async 懒加载
    loaded = (
        await db_session.execute(
            select(TaskRun).where(TaskRun.id == task.id).options(selectinload(TaskRun.steps))
        )
    ).scalar_one()
    await executor._mark_cancelled(db_session, loaded)
    await db_session.commit()

    row = await db_session.get(TaskRun, int(task.id))
    assert row.status == "cancel_requested"
    assert row.billing_status == "frozen"
    assert user.frozen_fen == need
    assert user.balance_fen == 100_000 - need
    refund_count = (
        await db_session.execute(
            select(WalletLedger).where(
                WalletLedger.ref_type == "task_run",
                WalletLedger.ref_id == str(task.id),
                WalletLedger.kind.in_(("unfreeze", "settle")),
            )
        )
    ).scalars().all()
    assert refund_count == []


@pytest.mark.asyncio
async def test_mark_cancelled_after_window_refunds_full_freeze(db_session: AsyncSession) -> None:
    """窗口已过（收尾协程未交付）：正常取消收敛，全额退款。"""
    user = await make_user(db_session, balance_fen=100_000)
    task, need = await _frozen_fragment_task(db_session, user)
    task.status = "cancel_requested"
    task.cancel_requested = True
    task.payload = {FINALIZING_UNTIL_KEY: (datetime.now(UTC) - timedelta(minutes=11)).isoformat()}
    await db_session.commit()

    loaded = (
        await db_session.execute(
            select(TaskRun).where(TaskRun.id == task.id).options(selectinload(TaskRun.steps))
        )
    ).scalar_one()
    await executor._mark_cancelled(db_session, loaded)
    await db_session.commit()

    row = await db_session.get(TaskRun, int(task.id))
    assert row.status == "cancelled"
    assert row.billing_status == "settled"
    assert row.billing_refunded_fen == need
    assert user.frozen_fen == 0
    assert user.balance_fen == 100_000


@pytest.mark.asyncio
async def test_finalized_cancel_settlement_is_idempotent(db_session: AsyncSession) -> None:
    """重复收敛不得二次退款（钱包侧 prior 流水门闩 + settled 门闩）。"""
    user = await make_user(db_session, balance_fen=100_000)
    task, need = await _frozen_fragment_task(db_session, user)
    charge = max(1, need - 100)
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

    assert await drama_jobs._settle_cancelled_after_finalized(db_session, int(task.id)) is True
    await db_session.commit()
    # 竞态：收尾协程/取消路径再收敛一次
    assert await drama_jobs._settle_cancelled_after_finalized(db_session, int(task.id)) is True
    await db_session.commit()

    unfreeze = (
        await db_session.execute(
            select(WalletLedger).where(
                WalletLedger.ref_type == "task_run",
                WalletLedger.ref_id == str(task.id),
                WalletLedger.kind == "unfreeze",
            )
        )
    ).scalars().all()
    assert len(unfreeze) == 1
    assert unfreeze[0].delta_fen == need - charge
    assert user.balance_fen == 100_000 - charge
    assert user.frozen_fen == 0
