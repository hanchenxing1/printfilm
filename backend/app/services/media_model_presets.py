"""站点预设模型清单 + 按模型生成参数白名单。"""

from __future__ import annotations

from typing import Any

from app.schemas_routing import LogicalModelCapability
from app.services.model_routing_config import normalize_model_name

# 管理端四下拉 + 渠道 models 硬编码白名单（含前台展示文案）
PRESET_MODELS: dict[LogicalModelCapability, tuple[dict[str, str], ...]] = {
    "text": (
        {
            "id": "kimi-k2.6",
            "label": "Kimi K2.6",
            "note": "默认剧本/分镜，中文长上下文表现稳定",
            "pricing_hint": "适合长剧本",
        },
        {
            "id": "deepseek-v4-pro",
            "label": "DeepSeek V4 Pro",
            "note": "推理强、性价比高，适合扩写与润色",
            "pricing_hint": "通常更省",
        },
        {
            "id": "gpt-5.5",
            "label": "GPT 5.5",
            "note": "综合能力强，复杂指令与英文场景更稳",
            "pricing_hint": "相对更贵",
        },
    ),
    "image": (
        {
            "id": "seedream-5-0-pro",
            "label": "Seedream 5.0 Pro",
            "note": "角色一致性好，适合漫剧定妆与分镜静帧",
            "pricing_hint": "清晰度越高越贵",
            "eta_hint": "约 20–60 秒/张",
        },
        {
            "id": "gpt-image-2",
            "label": "GPT Image 2",
            "note": "细节与文字表现好，适合海报与精细静帧",
            "pricing_hint": "清晰度越高越贵",
            "eta_hint": "约 30–90 秒/张",
        },
    ),
    "video": (
        {
            "id": "seedance-2-0",
            "label": "Seedance 2.0",
            "note": "标准成片，运镜较稳；最高 720p",
            "pricing_hint": "清晰度越高越贵",
            "eta_hint": "约 2–5 分钟/镜",
        },
        {
            "id": "seedance-2-0-mini",
            "label": "Seedance 2.0 Mini",
            "note": "更快更省，适合草稿与批量；最高 720p",
            "pricing_hint": "更省 · 清晰度越高越贵",
            "eta_hint": "约 1–3 分钟/镜",
        },
        {
            "id": "seedance-2-5",
            "label": "Seedance 2.5",
            "note": "成片首选，画质更好；支持到 1080p",
            "pricing_hint": "相对更贵 · 清晰度越高越贵",
            "eta_hint": "约 3–8 分钟/镜",
        },
        {
            "id": "MiniMax-H3",
            "label": "MiniMax H3",
            "note": "节奏感强、人物生动；4–15 秒，仅 720p",
            "pricing_hint": "出片偏慢",
            "eta_hint": "偏慢，4s 约 15 分钟起",
        },
    ),
    "audio": (
        {
            "id": "gemini-3.1-flash-tts",
            "label": "Gemini 3.1 Flash TTS",
            "note": "站点默认配音，语速自然、中文稳定",
            "pricing_hint": "",
            "eta_hint": "约数秒～十几秒",
        },
    ),
}

# 生图常用比例（与 Seedream 尺寸表交集）
IMAGE_ASPECT_RATIOS: tuple[str, ...] = (
    "auto",
    "1:1",
    "16:9",
    "9:16",
    "4:3",
    "3:4",
    "3:2",
    "2:3",
    "21:9",
)
# Pro / gpt-image：前端只给 1K/2K，避免选 3K 被静默降档
IMAGE_RESOLUTIONS_STANDARD: tuple[str, ...] = ("1K", "2K")

VIDEO_ASPECT_RATIOS: tuple[str, ...] = ("9:16", "16:9", "1:1")
VIDEO_RESOLUTIONS_FULL: tuple[str, ...] = ("480p", "720p", "1080p")
VIDEO_RESOLUTIONS_SAFE: tuple[str, ...] = ("480p", "720p")
# MiniMax-H3 当前渠道仅 720p
VIDEO_RESOLUTIONS_720_ONLY: tuple[str, ...] = ("720p",)


# 历史友好别名 → 预设规范 id（保存路由 / 目录去重用）
PRESET_MODEL_ALIASES: dict[str, str] = {
    "seedance-2.5": "seedance-2-5",
    "seedance2.5": "seedance-2-5",
    "seedance-2": "seedance-2-0",
    "seedance2": "seedance-2-0",
    "seedance-2.0": "seedance-2-0",
    "seedance2.0": "seedance-2-0",
    # 图模旧点分 id → TokenFree 规范 id
    "seedream-5.0": "seedream-5-0-pro",
    "seedream-5": "seedream-5-0-pro",
    "seedream5.0": "seedream-5-0-pro",
    "seedream5": "seedream-5-0-pro",
    "gpt-image-2-5": "gpt-image-2",
    "gpt-image-2.5": "gpt-image-2",
}


def preset_ids(capability: LogicalModelCapability) -> list[str]:
    """某能力下的预设上游 id。"""
    return [str(row["id"]) for row in PRESET_MODELS.get(capability, ())]


def resolve_preset_alias(model_id: str | None) -> str:
    """将历史别名映射到预设规范 id；无映射则原样返回。"""
    raw = (model_id or "").strip()
    if not raw:
        return ""
    key = normalize_model_name(raw)
    for alias, canonical in PRESET_MODEL_ALIASES.items():
        if normalize_model_name(alias) == key:
            return canonical
    return raw


def lookup_preset_row(model_id: str | None) -> dict[str, str] | None:
    """按 id（含别名）查找预设行。"""
    mid = normalize_model_name(resolve_preset_alias(model_id))
    if not mid:
        return None
    for rows in PRESET_MODELS.values():
        for row in rows:
            if normalize_model_name(row["id"]) == mid:
                return dict(row)
    return None


def preset_display_meta(model_id: str | None) -> dict[str, str]:
    """前台目录展示：友好名、介绍、资费与大致出片时长。"""
    row = lookup_preset_row(model_id)
    if not row:
        return {"label": "", "note": "", "pricing_hint": "", "eta_hint": ""}
    return {
        "label": str(row.get("label") or ""),
        "note": str(row.get("note") or ""),
        "pricing_hint": str(row.get("pricing_hint") or ""),
        "eta_hint": str(row.get("eta_hint") or ""),
    }


def all_preset_channel_models() -> list[str]:
    """写入 TokenFree 渠道的全部预设 id（文/图/视/音）。"""
    out: list[str] = []
    seen: set[str] = set()
    for cap in ("text", "image", "video", "audio"):
        for mid in preset_ids(cap):  # type: ignore[arg-type]
            key = normalize_model_name(mid)
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(mid)
    return out


def is_preset_model(capability: LogicalModelCapability, model_id: str | None) -> bool:
    """默认模型是否落在对应预设内（含历史别名）。"""
    mid = normalize_model_name(resolve_preset_alias(model_id))
    if not mid:
        return False
    return mid in {normalize_model_name(x) for x in preset_ids(capability)}


def clamp_default_to_preset(capability: LogicalModelCapability, model_id: str | None) -> str:
    """非法或不空缺省时落到该能力第一项预设。"""
    raw = resolve_preset_alias(model_id)
    if is_preset_model(capability, raw):
        # 返回预设表里的规范写法
        for mid in preset_ids(capability):
            if normalize_model_name(mid) == normalize_model_name(raw):
                return mid
    ids = preset_ids(capability)
    return ids[0] if ids else ""


def _is_minimax_h3(mid: str) -> bool:
    return "minimax" in mid and "h3" in mid.replace("-", "").replace("_", "")


def _is_seedance_mini(mid: str) -> bool:
    return "seedance" in mid and ("mini" in mid or "fast" in mid)


def _is_seedance_25(mid: str) -> bool:
    return "seedance" in mid and ("2.5" in mid or "2-5" in mid)


def _is_seedance_20(mid: str) -> bool:
    """Seedance 2.0 完整档（非 mini、非 2.5）。"""
    if "seedance" not in mid:
        return False
    if _is_seedance_mini(mid) or _is_seedance_25(mid):
        return False
    return (
        "2-0" in mid
        or "2.0" in mid
        or mid in {"seedance-2", "seedance2"}
        or mid.endswith("seedance-2")
    )


def model_generation_options(model_id: str | None) -> dict[str, Any]:
    """按模型返回前台可选参数；未知模型给保守默认。"""
    mid = normalize_model_name(resolve_preset_alias(model_id) or (model_id or ""))
    if not mid:
        return {}

    image_ids = {normalize_model_name(x) for x in preset_ids("image")}
    video_ids = {normalize_model_name(x) for x in preset_ids("video")}

    # 图像预设 / seedream / gpt-image
    if mid in image_ids or "seedream" in mid or mid.startswith("gpt-image"):
        return {
            "capability": "image",
            "allowed_aspect_ratios": list(IMAGE_ASPECT_RATIOS),
            "allowed_resolutions": list(IMAGE_RESOLUTIONS_STANDARD),
        }

    # 视频：预设表与 Seedance / MiniMax 优先
    if mid in video_ids or "seedance" in mid or _is_minimax_h3(mid):
        if _is_seedance_mini(mid):
            return {
                "capability": "video",
                "allowed_aspect_ratios": list(VIDEO_ASPECT_RATIOS),
                "allowed_resolutions": list(VIDEO_RESOLUTIONS_SAFE),
                "duration_min": 4,
                "duration_max": 30,
            }
        if _is_minimax_h3(mid):
            return {
                "capability": "video",
                "allowed_aspect_ratios": list(VIDEO_ASPECT_RATIOS),
                "allowed_resolutions": list(VIDEO_RESOLUTIONS_720_ONLY),
                "duration_min": 4,
                "duration_max": 15,
            }
        # 仅 Seedance 2.5 开放 1080p；2.0 及其它 Seedance 最高 720p
        if _is_seedance_25(mid):
            return {
                "capability": "video",
                "allowed_aspect_ratios": list(VIDEO_ASPECT_RATIOS),
                "allowed_resolutions": list(VIDEO_RESOLUTIONS_FULL),
                "duration_min": 4,
                "duration_max": 30,
            }
        if _is_seedance_20(mid) or "seedance" in mid:
            return {
                "capability": "video",
                "allowed_aspect_ratios": list(VIDEO_ASPECT_RATIOS),
                "allowed_resolutions": list(VIDEO_RESOLUTIONS_SAFE),
                "duration_min": 4,
                "duration_max": 30,
            }
        return {
            "capability": "video",
            "allowed_aspect_ratios": list(VIDEO_ASPECT_RATIOS),
            "allowed_resolutions": list(VIDEO_RESOLUTIONS_SAFE),
            "duration_min": 4,
            "duration_max": 30,
        }

    return {}
