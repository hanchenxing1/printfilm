# -*- coding: utf-8 -*-
"""科普流水线取消语义：异常必须传播到任务平台，regen 不得复活已取消项目。"""
from __future__ import annotations

import inspect
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Project, ProjectStatus, Shot, Template, User
from app.models_tasks import TaskRun
from app.services import pipeline
from app.services.pipeline import PipelineCancelled
from app.services.tasks.handlers import _await_kepu

from tests.conftest import make_user


@asynccontextmanager
async def _same_session(db: AsyncSession):
    """把 pipeline 内自开 session 钉到用例事务。"""
    yield db


async def _boom() -> None:
    raise PipelineCancelled("cancelled")


async def _ok() -> None:
    return None


def _fake_task(*, cancel_requested: bool) -> TaskRun:
    return SimpleNamespace(cancel_requested=cancel_requested, project_id=7)


async def test_await_kepu_maps_cancelled_when_requested() -> None:
    """任务已被请求取消：PipelineCancelled 收敛为 cancelled 结果。"""
    out = await _await_kepu(_fake_task(cancel_requested=True), _boom())
    assert out["cancelled"] is True
    assert out["project_id"] == 7


async def test_await_kepu_reraises_without_request() -> None:
    """未走取消流程却收到 PipelineCancelled（异常状态）：必须抛出，按失败收敛。"""
    with pytest.raises(PipelineCancelled):
        await _await_kepu(_fake_task(cancel_requested=False), _boom())


async def test_await_kepu_success_payload() -> None:
    out = await _await_kepu(_fake_task(cancel_requested=False), _ok(), shot_id=3)
    assert out == {"ok": True, "project_id": 7, "shot_id": 3}


def test_run_pipeline_reraises_after_cancel_side_effects() -> None:
    """源码守卫：run_pipeline 取消分支落库/推 SSE 后必须 re-raise（旧实现吞异常致误扣费）。"""
    source = inspect.getsource(pipeline.run_pipeline)
    cancel_block = source.split("except (PipelineCancelled, asyncio.CancelledError):")[-1]
    cancel_block = cancel_block.split("except Exception", 1)[0]
    assert "raise" in cancel_block


async def test_regen_image_does_not_revive_cancelled_project(
    db_session: AsyncSession,
) -> None:
    """等待 AI 期间用户取消项目：结果不得写回、状态不得复活，但上游用量照记。"""
    user = await make_user(db_session)
    tpl = Template(id="tpl-cancel-1", name="取消测试模板", style_prefix="x")
    db_session.add(tpl)
    await db_session.flush()
    project = Project(
        user_id=user.id,
        template_id=tpl.id,
        source_text="测试",
        status=ProjectStatus.CANCELLED,
    )
    db_session.add(project)
    await db_session.flush()
    shot = Shot(project_id=project.id, shot_no=1, img_prompt="一只猫", status=ProjectStatus.IMAGING)
    shot.image_url = "/static/old.png"
    db_session.add(shot)
    await db_session.flush()

    fake_ark = SimpleNamespace(
        gen_image=AsyncMock(
            return_value=SimpleNamespace(local_url="/static/new.png", remote_url="http://up/new.png")
        )
    )
    record = AsyncMock()
    with (
        patch.object(pipeline, "AsyncSessionLocal", lambda: _same_session(db_session)),
        patch.object(pipeline, "get_ark", return_value=fake_ark),
        patch.object(pipeline, "image_refs_for_shot", return_value=[]),
        patch.object(pipeline, "previous_usable_shot", return_value=None),
        patch.object(pipeline, "_record_seedream_usage", record),
    ):
        with pytest.raises(PipelineCancelled):
            await pipeline.regen_shot_image(project.id, shot.id)

    # 显式选列重查，避免 expire 后同步属性访问触发懒加载
    from sqlalchemy import select

    row = (
        await db_session.execute(
            select(Shot.image_url, Shot.version).where(Shot.id == shot.id)
        )
    ).one()
    assert row.image_url == "/static/old.png"  # 新图未写回
    assert row.version == 1
    status = (
        await db_session.execute(select(Project.status).where(Project.id == project.id))
    ).scalar_one()
    assert status == ProjectStatus.CANCELLED  # 未复活
    record.assert_awaited_once()  # 上游真实成本仍记账
