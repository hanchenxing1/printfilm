"""Selector 分派回归：非 drama 的 awaiting_poll 任务不得进入 drama 轮询处理器。"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models_tasks import TaskRun
from app.services.tasks import poller as poller_mod

from tests.conftest import make_task, make_user


@asynccontextmanager
async def _same_session(db: AsyncSession):
    """把服务内 AsyncSessionLocal 钉到用例事务 session。"""
    yield db


@pytest.mark.asyncio
async def test_selector_only_dispatches_fragment_video_to_drama_poller(
    db_session: AsyncSession,
) -> None:
    """api/studio deferred 视频任务必须只走 ephemeral 轮询，不能被 drama poller 判失败。"""
    user = await make_user(db_session)
    now = datetime.now(UTC)
    # 漫剧分镜视频：唯一允许进入 drama poller 的任务
    drama_task = await make_task(
        db_session,
        user,
        domain="drama",
        task_type="fragment_video",
        status="awaiting_poll",
        provider_task_id="prov-drama-1",
    )
    # 开放 API / 工具的 deferred 视频：旧实现下会被误送 drama poller 并立即判失败
    api_task = await make_task(
        db_session,
        user,
        domain="api",
        task_type="v1_seedance",
        status="awaiting_poll",
        provider_task_id="prov-api-1",
    )
    drama_task.next_action_at = now - timedelta(seconds=1)
    api_task.next_action_at = now - timedelta(seconds=1)
    await db_session.commit()
    api_task_id = int(api_task.id)

    drama_poll = AsyncMock()
    with (
        patch("app.services.tasks.poller.AsyncSessionLocal", lambda: _same_session(db_session)),
        patch("app.services.drama.jobs.poll_fragment_video_task", drama_poll),
    ):
        await poller_mod._select_and_poll_due()

    called_ids = {call.args[0] for call in drama_poll.await_args_list}
    assert called_ids == {int(drama_task.id)}
    assert api_task_id not in called_ids


@pytest.mark.asyncio
async def test_selector_sql_filters_fragment_video_type() -> None:
    """源码守卫：到期查询必须带 task_type=fragment_video，避免回归成无 domain 过滤。"""
    captured: dict[str, object] = {}

    class _Result:
        def scalars(self):
            return self

        def all(self):
            return []

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def execute(self, stmt):
            captured["sql"] = str(stmt.compile(compile_kwargs={"literal_binds": True}))
            return _Result()

    with patch.object(poller_mod, "AsyncSessionLocal", _Session):
        await poller_mod._select_and_poll_due()

    assert "fragment_video" in str(captured["sql"])


@pytest.mark.asyncio
async def test_ephemeral_poller_respects_next_action_at_gate(
    db_session: AsyncSession,
) -> None:
    """next_action_at 在未来的在途任务本轮不查上游；NULL/到期才查。"""
    user = await make_user(db_session)
    now = datetime.now(UTC)

    due_task = await make_task(
        db_session,
        user,
        domain="api",
        task_type="v1_video",
        status="awaiting_poll",
        provider_task_id="prov-due",
    )
    waiting_task = await make_task(
        db_session,
        user,
        domain="studio",
        task_type="tool_video",
        status="awaiting_poll",
        provider_task_id="prov-wait",
    )
    due_task.billing_status = "frozen"
    waiting_task.billing_status = "frozen"
    due_task.next_action_at = now - timedelta(seconds=1)
    waiting_task.next_action_at = now + timedelta(minutes=5)
    await db_session.commit()

    upstream_poll = AsyncMock(return_value={"status": "running"})
    with (
        patch("app.services.tasks.poller.AsyncSessionLocal", lambda: _same_session(db_session)),
        patch("app.services.studio_tools.poll_video_task", upstream_poll),
    ):
        await poller_mod._poll_ephemeral_deferred_tasks()

    polled_users = [call.args[1] for call in upstream_poll.await_args_list]
    assert len(polled_users) == 1  # 仅到期任务查了上游
