"""生图预扣须能被注册赠金冻住，避免新用户一张图都出不了。"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.models_tasks import TaskRun
from app.services.billing.estimates import estimate_task_fen
from app.services.tokenfree_pricing import set_cached_rates


@pytest.mark.asyncio
async def test_asset_image_freeze_fits_signup_grant(monkeypatch):
    """2K sunburst 10 积分 → 35 分；乘 1.2 也不再套在按张价上。"""
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "billing_estimate_buffer", 1.2)
    monkeypatch.setattr(settings, "billing_signup_grant_fen", 500)
    monkeypatch.setattr(settings, "billing_markup", 1.0)
    monkeypatch.setattr(settings, "billing_usd_cny", 7.0)
    set_cached_rates(None)

    task = TaskRun(
        id=1,
        domain="drama",
        task_type="asset_image",
        requested_by=1,
        payload={},
    )
    fen = await estimate_task_fen(MagicMock(), task, settings=settings)
    assert fen == 35
    assert fen <= int(settings.billing_signup_grant_fen)


@pytest.mark.asyncio
async def test_tool_image_freeze_skips_estimate_buffer(monkeypatch):
    """工具中心生图同样按张价预扣，不乘缓冲。"""
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "billing_estimate_buffer", 1.2)
    monkeypatch.setattr(settings, "billing_markup", 1.0)
    monkeypatch.setattr(settings, "billing_usd_cny", 7.0)
    set_cached_rates(None)

    task = TaskRun(
        id=2,
        domain="studio",
        task_type="tool_image",
        requested_by=1,
        payload={},
    )
    fen = await estimate_task_fen(MagicMock(), task, settings=settings)
    assert fen == 35


@pytest.mark.asyncio
async def test_asset_image_3k_clamps_to_2k_sunburst(monkeypatch):
    """漫剧默认 3K 会在生成侧钳成 2K，预扣跟 2K 走，不误收 4K 档。"""
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "billing_estimate_buffer", 1.2)
    monkeypatch.setattr(settings, "billing_markup", 1.0)
    monkeypatch.setattr(settings, "billing_kie_fen_per_credit", 3.5)
    set_cached_rates(None)

    task = TaskRun(
        id=3,
        domain="drama",
        task_type="asset_image",
        requested_by=1,
        payload={"resolution": "3K"},
    )
    fen = await estimate_task_fen(MagicMock(), task, settings=settings)
    assert fen == 35


@pytest.mark.asyncio
async def test_tool_image_1k_uses_six_credits(monkeypatch):
    """1K 按 6 积分预扣 21 分。"""
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "billing_estimate_buffer", 1.2)
    monkeypatch.setattr(settings, "billing_markup", 1.0)
    monkeypatch.setattr(settings, "billing_kie_fen_per_credit", 3.5)
    set_cached_rates(None)

    task = TaskRun(
        id=4,
        domain="studio",
        task_type="tool_image",
        requested_by=1,
        payload={"size": "1K"},
    )
    fen = await estimate_task_fen(MagicMock(), task, settings=settings)
    assert fen == 21
