# -*- coding: utf-8 -*-
"""真人隐私拦截：持久跳过标记，后续轮次不再重提 Seedance。"""
from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Project, ProjectStatus, Shot, ShotStatus, Template
from app.services import pipeline
from app.services.kepu_stages import (
    VIDEO_SKIP_REASON_PRIVACY,
    resolve_kepu_billing_phase,
    shot_video_ready,
    shot_video_skipped,
)

from tests.conftest import make_user


@asynccontextmanager
async def _same_session(db: AsyncSession):
    """把 pipeline 内自开 session 钉到用例事务。"""
    yield db


def test_skipped_shot_counts_as_video_ready() -> None:
    """带隐私跳过标记的镜头视为视频阶段已收敛，不再预估/重提。"""
    skipped = SimpleNamespace(video_url=None, video_skip_reason=VIDEO_SKIP_REASON_PRIVACY)
    normal = SimpleNamespace(video_url=None, video_skip_reason=None)
    assert shot_video_skipped(skipped)
    assert shot_video_ready(skipped)
    assert not shot_video_ready(normal)


async def test_phase_resolves_when_all_videos_skipped(
    db_session: AsyncSession, monkeypatch, tmp_path
) -> None:
    """全部镜头跳过视频后，下一阶段直接是 compose。"""
    (tmp_path / "full_narration.mp3").write_bytes(b"x" * 3000)
    monkeypatch.setattr("app.services.storage.project_dir", lambda _pid: tmp_path)
    user = await make_user(db_session)
    tpl = Template(id="tpl-privacy-1", name="隐私模板", style_prefix="x", seedance_config={})
    db_session.add(tpl)
    await db_session.flush()
    project = Project(
        user_id=user.id,
        template_id=tpl.id,
        source_text="测试",
        pipeline_mode="full",
        status=ProjectStatus.VIDEOING,
    )
    db_session.add(project)
    await db_session.flush()
    shot = Shot(
        project_id=project.id,
        shot_no=1,
        image_url="/static/p.png",
        video_url=None,
        video_skip_reason=VIDEO_SKIP_REASON_PRIVACY,
        status=ShotStatus.IMAGE_READY,
    )
    db_session.add(shot)
    await db_session.commit()

    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    loaded = (
        await db_session.execute(
            select(Project)
            .where(Project.id == project.id)
            .options(selectinload(Project.shots))
        )
    ).scalar_one()
    assert resolve_kepu_billing_phase(loaded) == "compose"


@pytest.mark.asyncio
async def test_parallel_videos_does_not_resubmit_skipped_shot(
    db_session: AsyncSession,
) -> None:
    """已标记隐私跳过的镜头走静图短路，绝不重新调用上游生视频。"""
    user = await make_user(db_session)
    tpl = Template(id="tpl-privacy-2", name="隐私模板2", style_prefix="x", seedance_config={})
    db_session.add(tpl)
    await db_session.flush()
    project = Project(
        user_id=user.id,
        template_id=tpl.id,
        source_text="测试",
        pipeline_mode="full",
        status=ProjectStatus.VIDEOING,
    )
    db_session.add(project)
    await db_session.flush()
    db_session.add_all(
        [
            Shot(
                project_id=project.id,
                shot_no=1,
                image_url="/static/p1.png",
                video_url="/static/v1.mp4",
                last_frame_url="/static/lf1.png",
                status=ShotStatus.VIDEO_READY,
            ),
            Shot(
                project_id=project.id,
                shot_no=2,
                image_url="/static/p2.png",
                video_url=None,
                video_skip_reason=VIDEO_SKIP_REASON_PRIVACY,
                status=ShotStatus.IMAGE_READY,
            ),
        ]
    )
    await db_session.commit()

    messages: list[str] = []

    async def _collect(_pid: int, payload: dict) -> None:
        messages.append(str(payload.get("message") or ""))

    ark = SimpleNamespace(
        gen_and_wait_video=AsyncMock(
            side_effect=AssertionError("隐私跳过镜头不得重新提交 Seedance")
        )
    )
    with (
        patch.object(pipeline, "AsyncSessionLocal", lambda: _same_session(db_session)),
        patch.object(pipeline, "publish_progress", _collect),
        patch.object(pipeline, "get_ark", return_value=ark),
    ):
        await pipeline._parallel_videos(project.id)

    assert any("已跳过 AI 视频" in m for m in messages)
    ark.gen_and_wait_video.assert_not_called()
