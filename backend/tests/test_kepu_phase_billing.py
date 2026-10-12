# -*- coding: utf-8 -*-
"""科普分阶段预扣：确认分镜时不应一次锁全片视频费用。"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.config import get_settings
from app.models_tasks import TaskRun
from app.services.billing.estimates import estimate_phase_fen, estimate_task_fen
from app.services.kepu_stages import (
    normalize_kepu_pipeline_phase,
    resolve_kepu_billing_phase,
)


def _shot(**kwargs):
    defaults = {
        "image_url": None,
        "image_ark_url": None,
        "audio_url": None,
        "video_url": None,
        "duration": 10.0,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _project(shots, pipeline_mode="full", project_id=1, resolution_mode="preview"):
    return SimpleNamespace(
        id=project_id,
        shots=shots,
        pipeline_mode=pipeline_mode,
        resolution_mode=resolution_mode,
    )


def test_resolve_phase_script_when_no_shots() -> None:
    assert resolve_kepu_billing_phase(_project([])) == "script"


def test_resolve_phase_assets_after_storyboard() -> None:
    shots = [_shot() for _ in range(7)]
    assert resolve_kepu_billing_phase(_project(shots)) == "assets"


def test_resolve_phase_videos_after_assets(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.kepu_stages.project_audio_ready",
        lambda _project: True,
    )
    shots = [_shot(image_url="/i.png", audio_url="/a.wav") for _ in range(7)]
    assert resolve_kepu_billing_phase(_project(shots)) == "videos"


def test_resolve_phase_videos_when_continuous_audio_ok(monkeypatch) -> None:
    """整片旁白文件就绪但 shot.audio_url 为空时，应与 pipeline 一样进入 videos。"""
    monkeypatch.setattr(
        "app.services.kepu_stages.continuous_narration_ok",
        lambda _pid: True,
    )
    shots = [_shot(image_url="/i.png") for _ in range(3)]
    assert resolve_kepu_billing_phase(_project(shots)) == "videos"


def test_resolve_phase_videos_when_native_audio_and_images() -> None:
    """Seedance 内置口播：有图即可进 videos，不依赖外部 TTS 文件。"""
    shots = [_shot(image_url="/i.png") for _ in range(3)]
    assert resolve_kepu_billing_phase(_project(shots)) == "videos"


def test_resolve_phase_assets_when_audio_url_but_file_bad(monkeypatch) -> None:
    """回退外部 TTS 时：仅有 audio_url 但文件不可用，仍留在 assets。"""
    settings = get_settings()
    monkeypatch.setattr(settings, "kepu_seedance_native_audio", False)
    monkeypatch.setattr(
        "app.services.kepu_stages.continuous_narration_ok",
        lambda _pid: False,
    )
    monkeypatch.setattr(
        "app.services.kepu_stages.shot_audio_file_ok",
        lambda _shot: False,
    )
    shots = [_shot(image_url="/i.png", audio_url="/missing.wav") for _ in range(2)]
    assert resolve_kepu_billing_phase(_project(shots)) == "assets"


def test_resolve_phase_compose_when_full_ready(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.kepu_stages.project_audio_ready",
        lambda _project: True,
    )
    shots = [
        _shot(image_url="/i.png", audio_url="/a.wav", video_url="/v.mp4") for _ in range(3)
    ]
    assert resolve_kepu_billing_phase(_project(shots)) == "compose"


def test_produce_estimate_is_assets_not_full_video() -> None:
    """确认分镜时 phase=produce 应只估出图段，远小于含视频的全片预扣。"""
    settings = get_settings()
    shots = [_shot(duration=10.0) for _ in range(7)]
    project = _project(shots)
    assets = estimate_phase_fen(project, "assets", settings=settings)
    videos = estimate_phase_fen(project, "videos", settings=settings)
    produce = estimate_phase_fen(project, "produce", settings=settings)
    legacy_full = assets + videos
    assert produce == assets
    assert produce < legacy_full
    assert videos > assets


def test_videos_estimate_only_remaining_shots() -> None:
    settings = get_settings()
    shots = [
        _shot(image_url="/i.png", audio_url="/a.wav", video_url="/done.mp4", duration=10),
        _shot(image_url="/i.png", audio_url="/a.wav", duration=10),
        _shot(image_url="/i.png", audio_url="/a.wav", duration=10),
    ]
    one = estimate_phase_fen(
        _project([_shot(image_url="/i.png", audio_url="/a.wav", duration=10)]),
        "videos",
        settings=settings,
    )
    two = estimate_phase_fen(_project(shots), "videos", settings=settings)
    # 每镜 ceil 后再乘 buffer，两镜合计可能差 1 分
    assert abs(two - one * 2) <= 1


def test_videos_estimate_hd_doubles_480p_preview() -> None:
    """HD 且配置 480p 时预扣按 720p（×2）。"""
    settings = get_settings()
    settings.ark_video_resolution = "480p"
    settings.billing_estimate_buffer = 1.0
    settings.model_video = "seedance-2-5"
    shots = [_shot(image_url="/i.png", audio_url="/a.wav", duration=5)]
    preview = estimate_phase_fen(_project(shots), "videos", settings=settings)
    hd = estimate_phase_fen(
        _project(shots, resolution_mode="hd"),
        "videos",
        settings=settings,
    )
    assert hd == preview * 2


@pytest.mark.asyncio
async def test_shot_regen_video_estimate_uses_project_hd() -> None:
    """单镜重生成视频预扣跟随项目 HD（480p→720p）。"""
    settings = get_settings()
    settings.ark_video_resolution = "480p"
    settings.billing_estimate_buffer = 1.0
    settings.model_video = "seedance-2-5"
    db = MagicMock()
    db.get = AsyncMock(return_value=SimpleNamespace(resolution_mode="hd"))
    task = TaskRun(
        id=9,
        domain="kepu",
        task_type="shot_regen_video",
        requested_by=1,
        project_id=3,
        payload={"duration": 5},
    )
    hd = await estimate_task_fen(db, task, settings=settings)
    db.get = AsyncMock(return_value=SimpleNamespace(resolution_mode="preview"))
    preview = await estimate_task_fen(db, task, settings=settings)
    assert hd == preview * 2


def test_normalize_produce_maps_to_current_phase(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.kepu_stages.project_audio_ready",
        lambda _project: True,
    )
    shots = [_shot(image_url="/i.png", audio_url="/a.wav") for _ in range(2)]
    project = _project(shots)
    assert normalize_kepu_pipeline_phase("produce", project) == "videos"
    assert normalize_kepu_pipeline_phase("assets", project) == "assets"
