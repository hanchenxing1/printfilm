"""取消全部漫剧分镜视频必须限定在当前用户范围内。"""
from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models_drama import DramaEpisode, DramaEpisodeFragment, DramaProject
from app.services.drama.jobs import cancel_all_episode_video_jobs

from tests.conftest import make_user


@asynccontextmanager
async def _same_session(db: AsyncSession):
    """把 jobs 内自开 session 钉到用例事务。"""
    yield db


async def _make_running_fragment(db: AsyncSession, user, *, title: str) -> DramaEpisodeFragment:
    """构造 用户→项目→分集→一条生成中分镜。"""
    project = DramaProject(user_id=user.id, title=title)
    db.add(project)
    await db.flush()
    episode = DramaEpisode(project_id=project.id, name="第 1 集")
    db.add(episode)
    await db.flush()
    fragment = DramaEpisodeFragment(
        episode_id=episode.id,
        sort_order=1,
        content="测试镜头",
        params={"generation": {"status": "running"}},
    )
    db.add(fragment)
    await db.flush()
    return fragment


@pytest.mark.asyncio
async def test_cancel_all_only_affects_requesting_user(db_session: AsyncSession) -> None:
    """用户 A 取消全部不得把用户 B 在生成的分镜置 cancelled。"""
    user_a = await make_user(db_session)
    user_b = await make_user(db_session)
    frag_a = await _make_running_fragment(db_session, user_a, title="A 的漫剧")
    frag_b = await _make_running_fragment(db_session, user_b, title="B 的漫剧")
    await db_session.commit()

    with patch(
        "app.services.drama.jobs.AsyncSessionLocal", lambda: _same_session(db_session)
    ):
        result = await cancel_all_episode_video_jobs(user_a.id)

    # 显式选列重查，避免 expire 后同步属性访问触发懒加载
    rows = dict(
        (
            await db_session.execute(
                select(DramaEpisodeFragment.id, DramaEpisodeFragment.params).where(
                    DramaEpisodeFragment.id.in_([frag_a.id, frag_b.id])
                )
            )
        )
        .tuples()
        .all()
    )
    assert rows[frag_a.id]["generation"]["status"] == "cancelled"
    assert result["fragments"] == 1
    # 关键回归：其他用户的分镜保持生成中
    assert rows[frag_b.id]["generation"]["status"] == "running"
