# -*- coding: utf-8 -*-
"""科普流水线阶段判定：计费预扣与 pipeline 共用同一套就绪规则。"""
from __future__ import annotations

from typing import Any

from app.services import storage
from app.services.ffmpeg_compose import is_near_silent_audio


# 真人隐私被 Seedance 拦截、确认跳过 AI 视频（成片用静图）的镜头标记
VIDEO_SKIP_REASON_PRIVACY = "privacy"


def _is_image_text(project: Any) -> bool:
    return (getattr(project, "pipeline_mode", None) or "full") == "image_text"


def shot_image_ready(shot: Any) -> bool:
    """分镜是否已有可用分镜图。"""
    return bool(getattr(shot, "image_url", None) or getattr(shot, "image_ark_url", None))


def shot_video_skipped(shot: Any) -> bool:
    """分镜是否被确认跳过 AI 视频（如真人隐私拦截），无需再提交上游。"""
    return getattr(shot, "video_skip_reason", None) == VIDEO_SKIP_REASON_PRIVACY


def shot_video_ready(shot: Any) -> bool:
    """分镜视频是否已收敛：已有视频，或已确认跳过（隐私拦截后用静图合成）。"""
    return bool(getattr(shot, "video_url", None)) or shot_video_skipped(shot)


def shot_audio_file_ok(shot: Any) -> bool:
    """单镜旁白文件存在且非近静音（与 pipeline _resume_plan 一致）。"""
    audio_url = getattr(shot, "audio_url", None)
    if not audio_url:
        return False
    path = storage.local_path_from_url(str(audio_url))
    if not path or not path.exists():
        return False
    return not is_near_silent_audio(path)


def continuous_narration_ok(project_id: int) -> bool:
    """整片连贯旁白文件是否可用（与 pipeline _continuous_audio_ok 一致）。"""
    path = storage.project_dir(int(project_id)) / "full_narration.mp3"
    return path.exists() and path.stat().st_size > 2000 and not is_near_silent_audio(path)


def project_audio_ready(project: Any) -> bool:
    """项目旁白是否就绪：视频内置口播无需外部 TTS；否则整片/分镜旁白文件 OK。"""
    # full + Seedance 内置口播：assets 阶段不强制外部配音
    if not _is_image_text(project):
        try:
            from app.config import get_settings

            if bool(getattr(get_settings(), "kepu_seedance_native_audio", True)):
                return True
        except Exception:  # noqa: BLE001
            # 配置异常时不 fail-open，避免误跳过外部 TTS
            pass
    project_id = getattr(project, "id", None)
    if project_id is not None and continuous_narration_ok(int(project_id)):
        return True
    shots = list(getattr(project, "shots", None) or [])
    return bool(shots) and all(shot_audio_file_ok(s) for s in shots)


def resolve_kepu_billing_phase(project: Any) -> str:
    """按分镜进度解析下一段：script | assets | videos | compose。"""
    shots = list(getattr(project, "shots", None) or [])
    if not shots:
        return "script"
    image_text = _is_image_text(project)
    need_images = any(not shot_image_ready(s) for s in shots)
    need_audio = not project_audio_ready(project)
    if need_images or need_audio:
        return "assets"
    if not image_text and any(not shot_video_ready(s) for s in shots):
        return "videos"
    return "compose"


def normalize_kepu_pipeline_phase(phase: str | None, project: Any | None = None) -> str:
    """规范化任务 phase；produce 兼容映射到当前应执行的下一段。"""
    raw = (phase or "").strip().lower()
    if raw == "produce":
        if project is None:
            return "assets"
        return resolve_kepu_billing_phase(project)
    if raw in {"script", "assets", "videos", "compose"}:
        return raw
    if project is not None:
        return resolve_kepu_billing_phase(project)
    return "assets"
