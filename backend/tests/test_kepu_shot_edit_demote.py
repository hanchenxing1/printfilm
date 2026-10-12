# -*- coding: utf-8 -*-
"""PATCH 分镜：改旁白作废整片连贯音轨，任何编辑都要把终态打回对应阶段。"""
from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.projects import update_shot
from app.models import Project, ProjectStatus, Shot, ShotStatus, Template
from app.schemas import ShotUpdate

from tests.conftest import make_user


async def _make_done_project(db: AsyncSession, user, tmp_path: Path) -> tuple[Project, Shot, Shot]:
    """构造 DONE 项目：两镜均有图/视频/配音，整片连贯音轨文件存在。"""
    tpl = Template(id="tpl-demote-1", name="作废测试模板", style_prefix="x")
    db.add(tpl)
    await db.flush()
    project = Project(
        user_id=user.id,
        template_id=tpl.id,
        source_text="测试",
        status=ProjectStatus.DONE,
        final_video_url="/static/final.mp4",
    )
    db.add(project)
    await db.flush()
    shots = []
    for no in (1, 2):
        shot = Shot(
            project_id=project.id,
            shot_no=no,
            narration=f"旧旁白{no}",
            image_url=f"/static/p{project.id}/old_{no}.png",
            image_ark_url=f"http://up/old_{no}.png",
            video_url=f"/static/p{project.id}/v_{no}.mp4",
            audio_url=f"/static/p{project.id}/full_narration.mp3",
            status=ShotStatus.VIDEO_READY,
        )
        db.add(shot)
        shots.append(shot)
    await db.flush()
    narration = tmp_path / "full_narration.mp3"
    narration.write_bytes(b"x" * 3000)
    return project, shots[0], shots[1]


@pytest.mark.asyncio
async def test_narration_edit_invalidates_continuous_audio(
    db_session: AsyncSession, monkeypatch, tmp_path
) -> None:
    """改旁白后：旧整片音轨删除、所有镜头 audio_url 清空、成片作废、状态回退。"""
    user = await make_user(db_session)
    project, shot1, shot2 = await _make_done_project(db_session, user, tmp_path)
    monkeypatch.setattr(
        "app.services.storage.project_dir", lambda _pid: tmp_path
    )

    await update_shot(
        project.id,
        shot1.id,
        ShotUpdate(narration="这是全新的旁白内容"),
        db=db_session,
        user=user,
    )

    assert not (tmp_path / "full_narration.mp3").exists()
    await db_session.refresh(shot1)
    await db_session.refresh(shot2)
    assert shot1.audio_url is None
    assert shot2.audio_url is None  # 整片连贯音轨，姊妹镜同步失效
    await db_session.refresh(project)
    assert project.final_video_url is None
    assert project.status == ProjectStatus.SCRIPT_READY  # assets 阶段：需重配音


@pytest.mark.asyncio
async def test_img_prompt_edit_demotes_done_project(db_session: AsyncSession) -> None:
    """改首帧提示词：清下游素材，DONE 项目必须回退而非保留完成态。"""
    user = await make_user(db_session)
    tpl = Template(id="tpl-demote-2", name="作图废测试模板", style_prefix="x")
    db_session.add(tpl)
    await db_session.flush()
    project = Project(
        user_id=user.id,
        template_id=tpl.id,
        source_text="测试",
        status=ProjectStatus.DONE,
        final_video_url="/static/final2.mp4",
    )
    db_session.add(project)
    await db_session.flush()
    shot = Shot(
        project_id=project.id,
        shot_no=1,
        img_prompt="旧图提示",
        image_url="/static/old.png",
        video_url="/static/old.mp4",
        status=ShotStatus.VIDEO_READY,
    )
    db_session.add(shot)
    await db_session.flush()

    await update_shot(
        project.id,
        shot.id,
        ShotUpdate(img_prompt="全新的画面要求"),
        db=db_session,
        user=user,
    )

    await db_session.refresh(shot)
    assert shot.image_url is None
    assert shot.video_url is None
    assert shot.status == ShotStatus.PENDING
    await db_session.refresh(project)
    assert project.final_video_url is None
    assert project.status != ProjectStatus.DONE
