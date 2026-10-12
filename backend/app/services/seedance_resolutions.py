# -*- coding: utf-8 -*-
"""Seedance / TokenFree 视频模型允许的清晰度（预设表优先，其余启发式）。"""
from __future__ import annotations

from app.services.model_routing_config import normalize_model_name

# 全量 UI / 白名单最高档（不上 4k）
ALL_VIDEO_RESOLUTIONS: tuple[str, ...] = ("480p", "720p", "1080p")
# mini / fast：渠道明确仅两档
SAFE_VIDEO_RESOLUTIONS: tuple[str, ...] = ("480p", "720p")
FULL_VIDEO_RESOLUTIONS: tuple[str, ...] = ("480p", "720p", "1080p")


def allowed_video_resolutions(model_id: str | None) -> list[str]:
    """按模型 id 返回允许的清晰度列表（从低到高）。

    优先读站点预设表；否则：
    - Seedance 2.5 → 含 1080p
    - MiniMax-H3 → 仅 720p
    - Seedance 2.0 / mini / fast / 其它 → 480p, 720p
    """
    mid = normalize_model_name(model_id or "")
    if not mid:
        return list(SAFE_VIDEO_RESOLUTIONS)

    from app.services.media_model_presets import model_generation_options

    opts = model_generation_options(model_id)
    raw = opts.get("allowed_resolutions") if isinstance(opts, dict) else None
    if isinstance(raw, list) and raw:
        filtered = [str(x).strip().lower() for x in raw if str(x).strip().lower() in ALL_VIDEO_RESOLUTIONS]
        if filtered:
            return filtered

    # MiniMax H3：仅 720p（须先于其它启发式，避免被当成 mini）
    if "minimax" in mid and "h3" in mid.replace("-", "").replace("_", ""):
        return ["720p"]

    # 仅 Seedance 2.5 含 1080p
    if "seedance" in mid and ("2.5" in mid or "2-5" in mid):
        return list(FULL_VIDEO_RESOLUTIONS)

    return list(SAFE_VIDEO_RESOLUTIONS)


def clamp_video_resolution(model_id: str | None, resolution: str | None) -> str:
    """将分辨率钳到该模型允许列表；非法或缺省取允许列表最高档。"""
    allowed = allowed_video_resolutions(model_id)
    raw = (resolution or "").strip().lower()
    if raw in allowed:
        return raw
    # 缺省 / 非法：取允许列表中最高档（通常 720p 或 1080p）
    return allowed[-1]


def video_duration_bounds(model_id: str | None) -> tuple[int, int]:
    """返回 (min, max) 秒；与站点 seedance_duration_* 取交集，缺省 4–30。"""
    from app.config import get_settings
    from app.services.media_model_presets import model_generation_options

    opts = model_generation_options(model_id)
    lo = int(opts.get("duration_min") or 4) if isinstance(opts, dict) else 4
    hi = int(opts.get("duration_max") or 30) if isinstance(opts, dict) else 30
    s = get_settings()
    site_lo = int(getattr(s, "seedance_duration_min", 4) or 4)
    site_hi = int(getattr(s, "seedance_duration_max", 30) or 30)
    lo = max(lo, site_lo)
    hi = min(hi, site_hi)
    if hi < lo:
        lo, hi = hi, lo
    return max(1, lo), max(lo, hi)


def clamp_video_duration(model_id: str | None, seconds: float | int | None) -> int:
    """将时长钳到模型允许区间。"""
    lo, hi = video_duration_bounds(model_id)
    try:
        n = int(round(float(seconds or lo)))
    except (TypeError, ValueError):
        n = lo
    return min(hi, max(lo, n))
