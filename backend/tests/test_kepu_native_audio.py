# -*- coding: utf-8 -*-
"""科普 full：Seedance 视频内置口播，跳过外部 TTS。"""
from __future__ import annotations

from types import SimpleNamespace

from app.config import get_settings
from app.services.kepu_stages import project_audio_ready
from app.services.pipeline import (
    _kepu_seedance_generate_audio,
    _kepu_seedance_native_audio,
    _kepu_seedance_sfx_audio,
)


def test_native_audio_default_on_for_full() -> None:
    project = SimpleNamespace(pipeline_mode="full")
    assert _kepu_seedance_native_audio(project) is True
    assert _kepu_seedance_sfx_audio(project) is False
    assert _kepu_seedance_generate_audio(project) is True


def test_native_audio_off_for_image_text() -> None:
    project = SimpleNamespace(pipeline_mode="image_text")
    assert _kepu_seedance_native_audio(project) is False
    assert _kepu_seedance_generate_audio(project) is False


def test_project_audio_ready_true_when_native(monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "kepu_seedance_native_audio", True)
    project = SimpleNamespace(id=1, pipeline_mode="full", shots=[SimpleNamespace()])
    assert project_audio_ready(project) is True


def test_sfx_fallback_when_native_off(monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "kepu_seedance_native_audio", False)
    monkeypatch.setattr(settings, "kepu_seedance_sfx_audio", True)
    project = SimpleNamespace(pipeline_mode="full")
    assert _kepu_seedance_native_audio(project) is False
    assert _kepu_seedance_sfx_audio(project) is True
    assert _kepu_seedance_generate_audio(project) is True
