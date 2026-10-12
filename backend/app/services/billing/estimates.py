# -*- coding: utf-8 -*-
"""按 TaskRun 估算预扣金额。"""
from __future__ import annotations

import math

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import Settings, get_settings
from app.models import Project
from app.models_tasks import TaskRun
from app.services.billing.pricing import charge_fen_for_tokens
from app.services.tokenfree_pricing import (
    charge_fen_official_image,
    charge_fen_official_llm,
    charge_fen_official_video,
    ensure_official_rates,
    resolve_billing_image_size,
)
from app.services.kepu_stages import (
    normalize_kepu_pipeline_phase,
    project_audio_ready,
    resolve_kepu_billing_phase,
    shot_image_ready,
    shot_video_ready,
)

__all__ = [
    "estimate_phase_fen",
    "estimate_task_fen",
    "resolve_kepu_billing_phase",
]


def _kepu_video_resolution(project: Project | None, settings: Settings) -> str:
    """科普成片清晰度：设置项；HD 且配置为 480p 时升到 720p（与 pipeline 一致）。"""
    raw = str(getattr(settings, "ark_video_resolution", "") or "480p")
    mode = str(getattr(project, "resolution_mode", "") or "")
    if mode == "hd" and raw.strip().lower() == "480p":
        return "720p"
    return raw


def _drama_video_resolution(payload: dict) -> str:
    """漫剧成片默认 720p，与前端与 asset_video 缺省一致。"""
    prepared = payload.get("prepared") if isinstance(payload.get("prepared"), dict) else {}
    raw = str((prepared or {}).get("resolution") or payload.get("resolution") or "").strip()
    return raw or "720p"


_VIDEO_SIZE_LABELS = {"480p", "720p", "1080p"}


def _payload_image_size(payload: dict) -> str:
    """从任务 payload 取生图清晰度；忽略 480p 等视频档。"""
    prepared = payload.get("prepared") if isinstance(payload.get("prepared"), dict) else {}
    gen = payload.get("generation") if isinstance(payload.get("generation"), dict) else {}
    canvas = payload.get("canvas") if isinstance(payload.get("canvas"), dict) else {}
    canvas_gen = canvas.get("generation") if isinstance(canvas.get("generation"), dict) else {}
    for val in (
        payload.get("size"),
        payload.get("image_size"),
        gen.get("size"),
        gen.get("resolution"),
        canvas_gen.get("size"),
        canvas_gen.get("resolution"),
        prepared.get("size"),
        prepared.get("image_size"),
    ):
        text = str(val or "").strip()
        if text:
            return text
    res = str(payload.get("resolution") or "").strip()
    if res and res.lower() not in _VIDEO_SIZE_LABELS:
        return res
    return ""


def _billing_image_size(settings: Settings, *, model: str = "", size: str = "") -> str:
    """计费用清晰度：与 ark 生成侧一致，Pro / sunburst 把 3K·4K 钳到 2K。"""
    return resolve_billing_image_size(settings, model=model, size=size)


def _buffered_fen(fen: int, settings: Settings) -> int:
    """token / 时长类估价乘缓冲；结果至少 1 分。"""
    buf = float(settings.billing_estimate_buffer or 1.2)
    return max(1, math.ceil(max(0, int(fen)) * buf))


def _catalog_image_fen(settings: Settings, *, model: str = "", size: str = "", payload: dict | None = None) -> int:
    """按张官价预扣，不再乘 1.2。缓冲是给 token 低估用的，张价已是结算价。"""
    body = payload if isinstance(payload, dict) else {}
    mid = model or settings.model_image
    resolved = _billing_image_size(settings, model=mid, size=size or _payload_image_size(body))
    return max(1, int(charge_fen_official_image(settings, model=mid, size=resolved)))


def _estimate_assets_fen(project: Project, settings: Settings) -> int:
    """只估尚未完成的出图 + 整片配音（不含镜头视频）。"""
    shots = list(project.shots or [])
    need_img = sum(1 for s in shots if not shot_image_ready(s))
    # 整片 TTS 一次估算；旁白已就绪（整片文件或全部镜头文件）则不再预扣
    need_tts = 0 if project_audio_ready(project) else 1
    if need_img <= 0 and need_tts <= 0:
        return 1
    total = 0
    for _ in range(max(need_img, 0)):
        total += _catalog_image_fen(settings)
    if need_tts > 0:
        n = max(len(shots), 1)
        _, c_tts = charge_fen_for_tokens(
            settings.billing_est_tts_tokens * n,
            "tts",
            settings=settings,
        )
        total += _buffered_fen(c_tts, settings)
    return max(total, 1)


def _estimate_videos_fen(project: Project, settings: Settings) -> int:
    """只估尚未出片的镜头视频。"""
    shots = [s for s in list(project.shots or []) if not shot_video_ready(s)]
    if not shots:
        return 1
    total = 0
    for sh in shots:
        secs = max(float(sh.duration or 4), 2.0)
        total += charge_fen_official_video(
            secs, settings, resolution=_kepu_video_resolution(project, settings)
        )
    return _buffered_fen(total, settings)


def estimate_phase_fen(project: Project, phase: str, settings: Settings | None = None) -> int:
    """科普 pipeline 阶段估算：script | assets | videos | compose | produce(兼容→下一段)。"""
    s = settings or get_settings()
    raw = normalize_kepu_pipeline_phase(phase, project)

    if raw == "script":
        charge = charge_fen_official_llm(s.billing_est_llm_tokens, s)
        return _buffered_fen(charge, s)

    if raw == "assets":
        return _estimate_assets_fen(project, s)

    if raw == "videos":
        return _estimate_videos_fen(project, s)

    if raw == "compose":
        return 1

    return _estimate_assets_fen(project, s)


async def estimate_task_fen(db: AsyncSession, task: TaskRun, settings: Settings | None = None) -> int:
    """按 domain + task_type 估算单任务预扣（分）。"""
    s = settings or get_settings()
    await ensure_official_rates(s)
    domain = (task.domain or "").strip()
    task_type = (task.task_type or "").strip()
    payload = task.payload if isinstance(task.payload, dict) else {}

    if domain == "kepu" and task_type == "project_pipeline":
        project_id = task.project_id or payload.get("project_id")
        if not project_id:
            charge = charge_fen_official_llm(s.billing_est_llm_tokens, s)
            return _buffered_fen(charge, s)
        result = await db.execute(
            select(Project).where(Project.id == int(project_id)).options(selectinload(Project.shots))
        )
        project = result.scalar_one_or_none()
        if not project:
            charge = charge_fen_official_llm(s.billing_est_llm_tokens, s)
            return _buffered_fen(charge, s)
        phase = str(payload.get("phase") or "script")
        return estimate_phase_fen(project, phase, settings=s)

    if domain == "kepu":
        if task_type in {"shot_regen_image"}:
            return _catalog_image_fen(s, payload=payload)
        if task_type in {"shot_regen_video"}:
            dur = float(payload.get("duration") or 5)
            project_id = task.project_id or payload.get("project_id")
            project = await db.get(Project, int(project_id)) if project_id else None
            c = charge_fen_official_video(
                max(dur, 2.0), s, resolution=_kepu_video_resolution(project, s)
            )
            return _buffered_fen(c, s)
        if task_type in {"shot_regen_audio", "project_regen_audio"}:
            _, c = charge_fen_for_tokens(s.billing_est_tts_tokens * 3, "tts", settings=s)
            return _buffered_fen(c, s)
        if task_type == "project_compose_only":
            return 1

    if domain == "drama":
        if task_type in {"script_summary", "fragment_plan", "agent_chat"}:
            c = charge_fen_official_llm(s.billing_est_llm_tokens, s)
            return _buffered_fen(c, s)
        if task_type == "episode_script":
            total_eps = int(payload.get("total") or payload.get("episode_count") or 1)
            c = charge_fen_official_llm(s.billing_est_llm_tokens * max(total_eps, 1), s)
            return _buffered_fen(c, s)
        if task_type in {"asset_image", "seed_assets"}:
            if task_type == "seed_assets":
                c = charge_fen_official_llm(s.billing_est_llm_tokens * 3, s)
                return _buffered_fen(c, s)
            return _catalog_image_fen(s, payload=payload)
        if task_type in {"asset_video", "fragment_video"}:
            dur = float(payload.get("duration_sec") or payload.get("duration") or 0)
            if dur <= 0 and isinstance(payload.get("prepared"), dict):
                dur = float(payload["prepared"].get("duration") or 0)
            if dur <= 0:
                frag_id = task.fragment_id or (
                    (payload.get("fragment_ids") or [None])[0]
                    if isinstance(payload.get("fragment_ids"), list)
                    else None
                )
                if frag_id:
                    from app.models_drama import DramaEpisodeFragment
                    from app.services.drama.fragment_content_duration import (
                        resolve_seedance_duration_from_content,
                    )

                    frag = await db.get(DramaEpisodeFragment, int(frag_id))
                    if frag is not None:
                        dur = float(
                            resolve_seedance_duration_from_content(
                                frag.content or "",
                                fallback=int(frag.duration_sec or 8),
                            )
                        )
            if dur <= 0:
                dur = 8.0
            c = charge_fen_official_video(
                max(dur, 2.0), s, resolution=_drama_video_resolution(payload)
            )
            c = _buffered_fen(c, s)
            if task_type == "fragment_video":
                c += max(1, _catalog_image_fen(s, payload=payload) // 2)
            return c
        if task_type == "voice_synthesis":
            _, c = charge_fen_for_tokens(s.billing_est_tts_tokens, "tts", settings=s)
            return _buffered_fen(c, s)
        if task_type in {"skill_optimize", "voice_prompt"}:
            c = charge_fen_official_llm(s.billing_est_llm_tokens, s)
            return _buffered_fen(c, s)

    if domain == "kepu" and task_type == "content_expand":
        c = charge_fen_official_llm(s.billing_est_llm_tokens, s)
        return _buffered_fen(c, s)

    if domain in {"api", "studio"}:
        if task_type in {"v1_image", "tool_image"}:
            return _catalog_image_fen(s, payload=payload)
        if task_type in {"v1_video", "v1_seedance", "tool_video"}:
            dur = float(payload.get("duration") or 5)
            c = charge_fen_official_video(
                max(dur, 2.0),
                s,
                resolution=str(payload.get("resolution") or "").strip() or "480p",
            )
            return _buffered_fen(c, s)

    c = charge_fen_official_llm(s.billing_est_llm_tokens, s)
    return _buffered_fen(c, s)
