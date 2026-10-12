"""fragment_video 预扣估算：时长来自正文 / payload。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models_tasks import TaskRun
from app.services.billing.estimates import estimate_task_fen


@pytest.mark.asyncio
async def test_fragment_video_estimate_uses_payload_duration_sec(monkeypatch):
    """有 duration_sec 时按秒数估算，不再默认 8s。"""
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "billing_est_seedance_tokens_per_sec", 32_000)
    monkeypatch.setattr(settings, "billing_estimate_buffer", 1.2)
    monkeypatch.setattr(settings, "billing_markup", 1.0)

    task = TaskRun(
        id=1,
        domain="drama",
        task_type="fragment_video",
        requested_by=1,
        payload={"duration_sec": 16, "fragment_ids": [9], "resolution": "720p"},
        fragment_id=9,
    )
    db = MagicMock()
    db.get = AsyncMock(return_value=None)

    fen8 = await estimate_task_fen(
        db,
        TaskRun(
            id=2,
            domain="drama",
            task_type="fragment_video",
            requested_by=1,
            payload={"duration_sec": 8, "resolution": "720p"},
            fragment_id=9,
        ),
        settings=settings,
    )
    fen16 = await estimate_task_fen(db, task, settings=settings)
    assert fen16 > fen8


@pytest.mark.asyncio
async def test_fragment_video_estimate_720p_doubles_480p(monkeypatch):
    """漫剧缺省 720p；视频部分相对 480p 翻倍，静帧加价不变。"""
    from app.config import get_settings
    from app.services.tokenfree_pricing import set_cached_rates

    settings = get_settings()
    monkeypatch.setattr(settings, "billing_estimate_buffer", 1.0)
    monkeypatch.setattr(settings, "billing_markup", 1.0)
    monkeypatch.setattr(settings, "billing_usd_cny", 7.0)
    monkeypatch.setattr(settings, "model_video", "seedance-2-5")
    set_cached_rates(None)
    db = MagicMock()
    db.get = AsyncMock(return_value=None)

    def _task(resolution: str | None) -> TaskRun:
        payload: dict = {"duration_sec": 5}
        if resolution:
            payload["resolution"] = resolution
        return TaskRun(
            id=4,
            domain="drama",
            task_type="fragment_video",
            requested_by=1,
            payload=payload,
            fragment_id=9,
        )

    fen_480 = await estimate_task_fen(db, _task("480p"), settings=settings)
    fen_720 = await estimate_task_fen(db, _task("720p"), settings=settings)
    fen_default = await estimate_task_fen(db, _task(None), settings=settings)
    # 5s Seedance 2.5：480p 336 分，720p 672 分；静帧加价相同
    assert fen_720 - fen_480 == 336
    assert fen_default == fen_720


@pytest.mark.asyncio
async def test_fragment_video_estimate_reads_fragment_content(monkeypatch):
    """无 payload duration 时从分镜正文 @duration 解析。"""
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "billing_est_seedance_tokens_per_sec", 32_000)
    monkeypatch.setattr(settings, "billing_estimate_buffer", 1.2)

    frag = SimpleNamespace(content="@duration:12 台词", duration_sec=8)
    db = MagicMock()
    db.get = AsyncMock(return_value=frag)

    task = TaskRun(
        id=3,
        domain="drama",
        task_type="fragment_video",
        requested_by=1,
        payload={"fragment_ids": [11]},
        fragment_id=11,
    )
    fen = await estimate_task_fen(db, task, settings=settings)
    assert fen > 0
    db.get.assert_awaited()
