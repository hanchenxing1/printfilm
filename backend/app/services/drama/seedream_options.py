"""Seedream 前端选项 → TokenFree model / size 解析。"""

from __future__ import annotations

import math
import re

from app.config import get_settings
from app.services.logical_model_router import resolve_logical_model_id, resolve_upstream_model

# SeedreamAspectRatio 支持的比例
SeedreamAspectRatio = str
# SeedreamResolution 清晰度
SeedreamResolution = str

# Seedream 5.0 Pro 自定义像素总面积上限（官方文档）
SEEDREAM_PRO_MAX_PIXELS = 4_624_220

# 官方 1K / 2K 推荐像素（均落在 Pro 上限内）
SEEDREAM_SIZE_1K: dict[str, str] = {
    "auto": "1K",
    "1:1": "1024x1024",
    "16:9": "1424x800",
    "9:16": "800x1424",
    "4:3": "1152x864",
    "3:4": "864x1152",
    "3:2": "1248x832",
    "2:3": "832x1248",
    "21:9": "1568x672",
}
SEEDREAM_SIZE_2K: dict[str, str] = {
    "auto": "2K",
    "1:1": "2048x2048",
    "16:9": "2816x1584",
    "9:16": "1584x2816",
    "4:3": "2368x1776",
    "3:4": "1776x2368",
    "3:2": "2496x1664",
    "2:3": "1664x2496",
    "21:9": "3136x1344",
}
# Lite / 4.5 可用的更高像素（超过 Pro 上限，仅非 Pro 模型使用）
SEEDREAM_SIZE_3K: dict[str, str] = {
    "auto": "3K",
    "1:1": "3072x3072",
    "16:9": "4096x2304",
    "21:9": "4704x2016",
    "9:16": "2304x4096",
    "4:3": "3456x2592",
    "3:4": "2592x3456",
}
SEEDREAM_SIZE_4K: dict[str, str] = {
    "auto": "4K",
    "1:1": "4096x4096",
    "16:9": "5404x3040",
    "21:9": "6198x2656",
    "9:16": "3040x5404",
    "4:3": "4694x3520",
    "3:4": "3520x4694",
}

SEEDREAM_SIZE_MAP: dict[str, dict[str, str]] = {
    "1K": SEEDREAM_SIZE_1K,
    "2K": SEEDREAM_SIZE_2K,
    "3K": SEEDREAM_SIZE_3K,
    "4K": SEEDREAM_SIZE_4K,
}

_PIXEL_SIZE_RE = re.compile(r"^(\d+)\s*[xX×]\s*(\d+)$")


# 判断接入点是否为 Seedream 5.0 Pro（仅支持 1K/2K，像素面积 ≤ 4624220）
def is_seedream_pro_model(model: str | None) -> bool:
    mid = (model or "").strip().lower()
    if not mid:
        return True
    # 非 Seedream（z-image / gpt-image / qwen-image 等）不按 Pro 规则钳制
    if "seedream" not in mid:
        return False
    if "seedream-4" in mid or "4.5" in mid or "4-5" in mid:
        return False
    if "lite" in mid:
        return False
    if "kie-" in mid:
        return False
    if "5-0-pro" in mid or "5.0-pro" in mid or "seedream-5.0" in mid:
        return True
    if "seedream-5" in mid or "seedream/5" in mid:
        return "lite" not in mid
    # 未标明版本的 seedream 默认按 Pro
    return True


def _is_compact_tokenfree_image_model(model: str | None) -> bool:
    """通义 z-image / qwen / banana 等不吃 Seedream 大像素，统一走 1K。"""
    mid = (model or "").strip().lower()
    if not mid:
        return False
    if "seedream" in mid or "gpt-image" in mid:
        return False
    return True


# 将超限 WxH 等比缩到 max_pixels 内（偶数边）
def clamp_seedream_pixel_size(
    size: str,
    *,
    max_pixels: int = SEEDREAM_PRO_MAX_PIXELS,
) -> str:
    raw = (size or "").strip()
    matched = _PIXEL_SIZE_RE.match(raw)
    if not matched:
        return raw
    width = int(matched.group(1))
    height = int(matched.group(2))
    if width <= 0 or height <= 0:
        return raw
    area = width * height
    if area <= max_pixels:
        return f"{width}x{height}"
    scale = math.sqrt(max_pixels / area)
    new_w = max(2, int(width * scale) // 2 * 2)
    new_h = max(2, int(height * scale) // 2 * 2)
    while new_w * new_h > max_pixels and (new_w > 2 or new_h > 2):
        if new_w >= new_h and new_w > 2:
            new_w -= 2
        elif new_h > 2:
            new_h -= 2
        else:
            break
    return f"{new_w}x{new_h}"


# 将前端模型 ID 解析为 TokenFree 上游模型名（逻辑模型与上游同名）
def resolve_seedream_model_endpoint(model_id: str | None) -> str:
    raw = (model_id or "").strip()
    settings = get_settings()
    mid = raw.lower()
    logical_id = resolve_logical_model_id("image", model_id)
    routed = resolve_upstream_model("image", logical_id)
    if routed:
        return routed
    if mid in {"", "seedream-5.0", "seedream-5", "5.0"}:
        return resolve_upstream_model("image", "seedream-5-0-pro") or settings.model_image or "seedream-5-0-pro"
    if mid in {"seedream-4.5", "seedream-4", "4.5"}:
        return (
            resolve_upstream_model("image", "seedream-4-5")
            or (settings.model_image_45 or "").strip()
            or settings.model_image
            or "seedream-4-5"
        )
    return model_id or settings.model_image or "seedream-5-0-pro"


# 将清晰度 + 比例解析为 size；Pro / 紧凑模型自动降档
def resolve_seedream_size(
    *,
    aspect_ratio: str | None = None,
    resolution: str | None = None,
    model_id: str | None = None,
) -> str:
    settings = get_settings()
    res = (resolution or "2K").strip().upper()
    if res not in SEEDREAM_SIZE_MAP:
        res = "2K"
    endpoint = resolve_seedream_model_endpoint(model_id) if model_id is not None else settings.model_image
    # z-image / qwen 等：大像素易触发 Invalid task protocol，强制 1K
    if _is_compact_tokenfree_image_model(endpoint):
        res = "1K"
    elif is_seedream_pro_model(endpoint) and res in {"3K", "4K"}:
        res = "2K"
    ratio = (aspect_ratio or "3:4").strip() or "3:4"
    mapped = SEEDREAM_SIZE_MAP[res].get(ratio)
    if not mapped:
        mapped = settings.ark_image_size or "2K"
    if is_seedream_pro_model(endpoint):
        if mapped.upper() in {"3K", "4K"}:
            mapped = "2K"
        return clamp_seedream_pixel_size(mapped)
    return mapped
