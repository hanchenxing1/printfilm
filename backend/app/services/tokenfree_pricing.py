"""TokenFree 公开 /api/pricing：推荐模型官方价与预估。"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import Settings, get_settings
from app.services.tokenfree_gateway import TOKENFREE_CONSOLE_URL, tokenfree_site_origin
from app.services.tokenfree_usage import usd_cny_rate

logger = logging.getLogger(__name__)

# New API：model_ratio=1 → $2 / 百万 tokens
NEWAPI_USD_PER_1M_AT_RATIO_1 = 2.0
# 视频价目常见占位倍率，不能当秒价
PLACEHOLDER_MODEL_RATIO = 37.5
_CACHE_TTL_SEC = 3600.0
_FAIL_TTL_SEC = 60.0
TOKENFREE_PRICING_PATH = "/api/pricing"
# LLM 预估按输入/输出拆分
LLM_PROMPT_SHARE = 0.7
# 费率表视频展示用的对照时长
VIDEO_RATE_SAMPLE_SECONDS = 5.0

# 本站视频结算参考价（16:9、无视频输入、5 秒）→ 各清晰度价（元）；用于展示与预扣
VENDOR_VIDEO_YUAN_5S_BY_RES: dict[str, dict[str, float]] = {
    "seedance-2-0": {"480p": 2.31, "720p": 4.97},
    "seedance-2-0-mini": {"480p": 0.80, "720p": 2.50},
    "seedance-2-5": {"480p": 3.36, "720p": 7.56, "1080p": 18.71},
}
# MiniMax-H3：约 $0.08/秒（768P）；本站仅开放 720p；人民币按 billing_usd_cny 折算
MINIMAX_H3_USD_PER_SEC_720P = 0.08


def minimax_h3_yuan_per_sec(settings: Settings | None = None) -> float:
    """MiniMax-H3 720p 结算参考秒价（人民币）。"""
    s = settings or get_settings()
    fx = float(getattr(s, "billing_usd_cny", 0) or 7.0)
    return MINIMAX_H3_USD_PER_SEC_720P * fx


# 兼容旧逻辑：480P 秒价（= 5 秒价 / 5）
VENDOR_VIDEO_YUAN_PER_SEC_480P = {
    mid: round(float(tiers["480p"]) / VIDEO_RATE_SAMPLE_SECONDS, 4)
    for mid, tiers in VENDOR_VIDEO_YUAN_5S_BY_RES.items()
    if "480p" in tiers
}
# 相对 480P 的预估倍率（无精确档位且走 token 回退时用；宁多冻）
VIDEO_RESOLUTION_MULT = {
    "480p": 1.0,
    "720p": 2.0,
    "1080p": 4.0,
}
_VIDEO_RES_ORDER = ("480p", "720p", "1080p")
# Kie sunburst 控制台档（USD / credits）；公开 /api/pricing 往往只有笼统 gpt-image-2-5
KIE_SUNBURST_USD_1K = 0.03
KIE_SUNBURST_USD_2K = 0.05
KIE_SUNBURST_USD_4K = 0.08
KIE_SUNBURST_CREDITS_1K = 6
KIE_SUNBURST_CREDITS_2K = 10
KIE_SUNBURST_CREDITS_4K = 16

# 产品里好用、目录有、方便去 TokenFree 核对的短名单
RECOMMENDED_MODELS: tuple[dict[str, Any], ...] = (
    {
        "id": "kimi-k2.6",
        "capability": "text",
        "label": "Kimi K2.6",
        "note": "默认剧本/分镜，中文长上下文",
        "recommended": True,
    },
    {
        "id": "deepseek-v3.2",
        "capability": "text",
        "label": "DeepSeek V3.2",
        "note": "便宜备选，扩写与闲聊",
        "recommended": False,
    },
    {
        "id": "qwen3.5-plus",
        "capability": "text",
        "label": "Qwen 3.5 Plus",
        "note": "便宜中文日常对话",
        "recommended": False,
    },
    {
        "id": "gpt-image-2",
        "capability": "image",
        "label": "GPT Image 2",
        "note": "KIE.AI Market default 渠道启用模型；计费按 Kie 2K 约 $0.05/张",
        "recommended": True,
    },
    {
        "id": "nano-banana-2",
        "capability": "image",
        "label": "Nano Banana 2",
        "note": "极便宜闪图，草稿/批量",
        "recommended": False,
    },
    {
        "id": "seedance-2-5",
        "capability": "video",
        "label": "Seedance 2.5",
        "note": "默认成片，最长约 30 秒",
        "recommended": True,
    },
    {
        "id": "seedance-2-0",
        "capability": "video",
        "label": "Seedance 2.0",
        "note": "标准 2.0，与 Mini 不同价档",
        "recommended": False,
    },
    {
        "id": "seedance-2-0-mini",
        "capability": "video",
        "label": "Seedance 2.0 Mini",
        "note": "更快更便宜的备选",
        "recommended": False,
    },
    {
        "id": "qwen-tts-2025-05-22",
        "capability": "audio",
        "label": "Qwen TTS",
        "note": "默认配音逻辑名；Ali /audio/speech 未实现，实际走 qwen3-omni-flash 流式 chat",
        "recommended": True,
    },
    {
        "id": "gemini-3.1-flash-tts",
        "capability": "audio",
        "label": "Gemini 3.1 Flash TTS",
        "note": "TokenFree 目录备选配音",
        "recommended": True,
    },
    {
        "id": "elevenlabs-tts",
        "capability": "audio",
        "label": "ElevenLabs TTS",
        "note": "TokenFree 目录备选配音",
        "recommended": False,
    },
)

_cache: dict[str, "OfficialRate"] | None = None
_cache_at: float = 0.0
_cache_failed: bool = False


@dataclass(frozen=True)
class OfficialRate:
    """一条 TokenFree 官方价。"""

    model: str
    billing: str
    usd_per_call: float
    cny_per_call: float
    cny_in_per_1m: float
    cny_out_per_1m: float
    model_ratio: float
    placeholder: bool
    tags: str
    endpoints: tuple[str, ...] = ()
    # 由 tags / supported_endpoint_types 推断；无强信号为 None（勿当成 text）
    capability: str | None = None


def capability_from_tokenfree_meta(
    tags: str = "",
    endpoints: list[str] | tuple[str, ...] | None = None,
) -> str | None:
    """从 TokenFree 价目 tags / supported_endpoint_types 推断能力；无强信号返回 None。"""
    raw_tags = (tags or "").strip().lower().replace("-", " ")
    parts = [p.strip() for p in raw_tags.replace("|", ",").split(",") if p.strip()]
    blob = " ".join(parts)
    ep = [str(x).strip().lower() for x in (endpoints or []) if str(x).strip()]

    if (
        any(token in blob for token in ("tts", "text to speech", "text to dialogue"))
        or "audio" in parts
        or any("audio" in e or "speech" in e for e in ep)
    ):
        return "audio"
    if (
        any("video" in e for e in ep)
        or "video" in parts
        or any(
            token in blob
            for token in (
                "text to video",
                "image to video",
                "video to video",
                "video editing",
                "lip sync",
            )
        )
    ):
        return "video"
    if (
        any("image" in e for e in ep)
        or "image-generation" in ep
        or "image" in parts
        or any(
            token in blob
            for token in ("text to image", "image to image", "image editing", "kie-image")
        )
    ):
        return "image"
    return None


def lookup_tokenfree_capability(model: str, rates: dict[str, OfficialRate] | None = None) -> str | None:
    """查价目缓存中的强分类；未收录或仅聊天类标签则返回 None。"""
    rate = lookup_rate(model, rates)
    if rate is None:
        return None
    return rate.capability


def tokenfree_pricing_url() -> str:
    """公开价目接口，无需 Key。"""
    return f"{tokenfree_site_origin()}{TOKENFREE_PRICING_PATH}"


def cached_rates() -> dict[str, OfficialRate]:
    """内存缓存；未拉过返回空。"""
    return dict(_cache or {})


def set_cached_rates(rates: dict[str, OfficialRate] | None) -> None:
    """写入缓存；None 表示测试清空，空 dict 表示负缓存。"""
    global _cache, _cache_at, _cache_failed
    if rates is None:
        _cache = None
        _cache_at = 0.0
        _cache_failed = False
        return
    _cache = dict(rates)
    _cache_at = time.monotonic()
    _cache_failed = False


def _mark_fetch_failed() -> None:
    """拉取失败：保留旧表，刷新时间戳，避免预扣每次打外网。"""
    global _cache, _cache_at, _cache_failed
    if _cache is None:
        _cache = {}
    _cache_at = time.monotonic()
    _cache_failed = True


def parse_pricing_item(item: dict[str, Any], *, usd_cny: float) -> OfficialRate | None:
    """把 /api/pricing 一行折成人民币。"""
    name = str(item.get("model_name") or "").strip()
    if not name:
        return None
    try:
        qt = int(item.get("quota_type") or 0)
        mr = float(item.get("model_ratio") or 0)
        cr = float(item.get("completion_ratio") or 0)
        mp = float(item.get("model_price") or 0)
        rate = max(0.01, float(usd_cny))
    except (TypeError, ValueError):
        return None
    tags = str(item.get("tags") or "")
    raw_eps = item.get("supported_endpoint_types") or []
    endpoints = tuple(str(x).strip() for x in raw_eps if str(x).strip()) if isinstance(raw_eps, list) else ()
    cap = capability_from_tokenfree_meta(tags, endpoints)
    if qt == 1:
        return OfficialRate(
            model=name,
            billing="per_call",
            usd_per_call=mp,
            cny_per_call=round(mp * rate, 4),
            cny_in_per_1m=0.0,
            cny_out_per_1m=0.0,
            model_ratio=0.0,
            placeholder=False,
            tags=tags,
            endpoints=endpoints,
            capability=cap,
        )
    return OfficialRate(
        model=name,
        billing="token",
        usd_per_call=0.0,
        cny_per_call=0.0,
        cny_in_per_1m=round(mr * NEWAPI_USD_PER_1M_AT_RATIO_1 * rate, 4),
        cny_out_per_1m=round(mr * cr * NEWAPI_USD_PER_1M_AT_RATIO_1 * rate, 4),
        model_ratio=mr,
        placeholder=abs(mr - PLACEHOLDER_MODEL_RATIO) < 0.01,
        tags=tags,
        endpoints=endpoints,
        capability=cap,
    )


def parse_pricing_payload(payload: dict[str, Any], settings: Settings | None = None) -> dict[str, OfficialRate]:
    """解析 TokenFree 价目 JSON。"""
    items = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return {}
    rate = usd_cny_rate(settings)
    out: dict[str, OfficialRate] = {}
    for raw in items:
        if not isinstance(raw, dict):
            continue
        parsed = parse_pricing_item(raw, usd_cny=rate)
        if parsed:
            out[parsed.model] = parsed
    return out


def lookup_rate(model: str, rates: dict[str, OfficialRate] | None = None) -> OfficialRate | None:
    """按模型 id 精确或忽略大小写查找。"""
    mid = (model or "").strip()
    table = rates if rates is not None else cached_rates()
    if not mid or not table:
        return None
    hit = table.get(mid)
    if hit:
        return hit
    key = mid.lower()
    for name, row in table.items():
        if name.lower() == key:
            return row
    return None


def video_catalog_id(model: str) -> str:
    """计费预估用：已知别名映射，未知 Seedance 回退 2.5。"""
    mapped = canonicalize_channel_model_id(model)
    if _is_canonical_seedance(mapped):
        return mapped
    return "seedance-2-5"


def _is_canonical_seedance(model: str) -> bool:
    """是否为 TokenFree 目录里的三档 Seedance id。"""
    return model in {"seedance-2-5", "seedance-2-0", "seedance-2-0-mini"}


def canonicalize_channel_model_id(model: str) -> str:
    """已知 Seedance 别名收到 TokenFree 目录 id；对不上则原样返回。"""
    mid = (model or "").strip()
    if "seedance" not in mid.lower():
        return mid
    low = mid.lower()
    if "mini" in low:
        return "seedance-2-0-mini"
    if any(token in low for token in ("2-5", "2.5", "260628")):
        return "seedance-2-5"
    if any(token in low for token in ("2-0", "2.0", "260128")):
        return "seedance-2-0"
    compact = low.replace("_", "-")
    if compact in {"seedance-2", "seedance2"} or compact.endswith("seedance-2"):
        return "seedance-2-0"
    return mid


def canonicalize_channel_models(models: list[str] | None) -> list[str]:
    """合并 Seedance 2.0 三档别名，保持原顺序。"""
    out: list[str] = []
    seen: set[str] = set()
    for raw in models or []:
        mid = canonicalize_channel_model_id(raw)
        if not mid or mid in seen:
            continue
        seen.add(mid)
        out.append(mid)
    return out


def _markup_charge(cost_fen: int, settings: Settings) -> int:
    """用户预扣金额 = 官方成本，不再乘倍率。"""
    from app.services.billing.pricing import user_charge_fen

    return user_charge_fen(cost_fen, settings)


def _kie_sunburst_tier(size: str | None = "") -> str:
    """Kie sunburst 清晰度档：1k / 2k / 4k。"""
    raw = (size or "").strip().upper().replace(" ", "")
    if raw.startswith("1K"):
        return "1k"
    if raw.startswith("3K") or raw.startswith("4K"):
        return "4k"
    if raw.startswith("2K"):
        return "2k"
    for sep in ("X", "×"):
        if sep not in raw:
            continue
        left, right = raw.split(sep, 1)
        if left.isdigit() and right.isdigit():
            pixels = int(left) * int(right)
            if pixels <= 1_200_000:
                return "1k"
            if pixels >= 8_000_000:
                return "4k"
            return "2k"
        break
    return "2k"


def kie_sunburst_usd_for_size(size: str | None = "") -> float:
    """Kie sunburst 按清晰度：1K $0.03 / 2K $0.05 / 3K·4K $0.08。"""
    return {
        "1k": KIE_SUNBURST_USD_1K,
        "2k": KIE_SUNBURST_USD_2K,
        "4k": KIE_SUNBURST_USD_4K,
    }[_kie_sunburst_tier(size)]


def kie_sunburst_credits_for_size(size: str | None = "") -> int:
    """Kie sunburst 积分：1K 6 / 2K 10 / 4K 16。"""
    return {
        "1k": KIE_SUNBURST_CREDITS_1K,
        "2k": KIE_SUNBURST_CREDITS_2K,
        "4k": KIE_SUNBURST_CREDITS_4K,
    }[_kie_sunburst_tier(size)]


def resolve_billing_image_size(settings: Settings, *, model: str = "", size: str = "") -> str:
    """计费用清晰度：与 ark / resolve_seedream_size 一致（紧凑→1K；Pro/gpt→≤2K）。"""
    from app.services.drama.seedream_options import (
        _is_compact_tokenfree_image_model,
        is_seedream_pro_model,
    )
    from app.services.tokenfree_image import tokenfree_working_image_model

    raw = (size or "").strip() or str(getattr(settings, "ark_image_size", "") or "2K")
    upstream = (model or getattr(settings, "model_image", "") or "").strip()
    working = tokenfree_working_image_model(upstream)
    # z-image / qwen 等生成侧强制 1K，计费同步
    if _is_compact_tokenfree_image_model(working) or _is_compact_tokenfree_image_model(upstream):
        return "1K"
    if (
        is_seedream_pro_model(upstream)
        or "sunburst" in working.lower()
        or "gpt-image" in working.lower()
    ):
        if raw.strip().upper() in {"3K", "4K"}:
            return "2K"
    return raw


def charge_fen_official_image(settings: Settings, *, model: str = "", size: str = "") -> int:
    """生图预估：gpt-image/sunburst 按 Kie 积分档；Seedream 与其它按 TokenFree 按张价。"""
    from app.services.billing.pricing import kie_credits_to_cost_fen
    from app.services.tokenfree_image import is_seedream_family, tokenfree_working_image_model

    raw_model = model or getattr(settings, "model_image", "") or ""
    mid = tokenfree_working_image_model(raw_model)
    resolved = resolve_billing_image_size(settings, model=raw_model, size=size)
    rate = lookup_rate(mid)
    use_kie_table = "sunburst" in mid.lower() or "gpt-image" in mid.lower()
    if use_kie_table:
        credits = kie_sunburst_credits_for_size(resolved or "2K")
        fen = kie_credits_to_cost_fen(credits, settings) or 1
        return _markup_charge(fen, settings)
    # Seedream / 其它：优先官方按张价
    if rate and rate.billing == "per_call" and rate.cny_per_call > 0:
        # round 避免 0.28*100 浮点成 28.0000000004 被 ceil 多收 1 分
        return _markup_charge(max(1, int(round(rate.cny_per_call * 100))), settings)
    # 无价目时：Seedream 与 gpt-image 共用保守 Kie 2K 档保底（非协议等价，仅防 0 冻）
    credits = kie_sunburst_credits_for_size(
        resolved if (use_kie_table or is_seedream_family(raw_model)) else "2K"
    )
    fen = kie_credits_to_cost_fen(credits, settings) or 1
    return _markup_charge(fen, settings)


def charge_fen_official_llm(tokens: int, settings: Settings, *, model: str = "") -> int:
    """LLM 预估：官方 in/out，按 70% 输入 / 30% 输出拆。"""
    from app.services.billing.pricing import charge_fen_for_tokens

    t = max(0, int(tokens))
    mid = (model or getattr(settings, "model_llm", "") or "kimi-k2.6").strip()
    rate = lookup_rate(mid)
    if t and rate and rate.billing == "token" and (rate.cny_in_per_1m or rate.cny_out_per_1m):
        prompt = int(t * LLM_PROMPT_SHARE)
        completion = t - prompt
        yuan = prompt / 1_000_000 * rate.cny_in_per_1m + completion / 1_000_000 * rate.cny_out_per_1m
        return _markup_charge(max(1, int(math.ceil(yuan * 100))), settings)
    _, charge = charge_fen_for_tokens(t, "llm_chat", settings=settings)
    return charge


def normalize_video_resolution(resolution: str | None, settings: Settings | None = None) -> str:
    """预估用清晰度：只认 480p/720p/1080p。"""
    raw = (resolution or "").strip().lower()
    if raw in VIDEO_RESOLUTION_MULT:
        return raw
    fallback = str(getattr(settings or get_settings(), "ark_video_resolution", "") or "480p").strip().lower()
    return fallback if fallback in VIDEO_RESOLUTION_MULT else "480p"


def _is_minimax_video_model(model: str) -> bool:
    """是否 MiniMax 视频模型（勿走 Seedance video_catalog_id 回退）。"""
    return "minimax" in (model or "").strip().lower()


def _resolve_vendor_video_key(model: str) -> str:
    """解析结算表用的规范 id；非 Seedance/表内 id 原样返回。"""
    mid = (model or "").strip()
    if not mid:
        return ""
    if mid in VENDOR_VIDEO_YUAN_5S_BY_RES:
        return mid
    mapped = canonicalize_channel_model_id(mid)
    if _is_canonical_seedance(mapped):
        return mapped
    return mid


def vendor_video_yuan_per_sec(
    model: str,
    resolution: str,
    settings: Settings | None = None,
) -> float | None:
    """本站视频结算参考秒价；无对应档位返回 None。"""
    mid = (model or "").strip()
    if not mid:
        return None
    res = normalize_video_resolution(resolution, settings)
    if _is_minimax_video_model(mid):
        return float(minimax_h3_yuan_per_sec(settings))
    key = _resolve_vendor_video_key(mid)
    tiers = VENDOR_VIDEO_YUAN_5S_BY_RES.get(key)
    if not tiers or res not in tiers:
        return None
    return float(tiers[res]) / VIDEO_RATE_SAMPLE_SECONDS


def format_video_pricing_hint(model: str) -> str:
    """前台/费率表：列出模型全部清晰度结算参考秒价。"""
    mid = (model or "").strip()
    if not mid:
        return ""
    if _is_minimax_video_model(mid):
        return f"约 ¥{minimax_h3_yuan_per_sec():.2f}/秒 · 仅 720p"
    key = _resolve_vendor_video_key(mid)
    tiers = VENDOR_VIDEO_YUAN_5S_BY_RES.get(key)
    if not tiers:
        return ""
    parts: list[str] = []
    for res in _VIDEO_RES_ORDER:
        yuan_5s = tiers.get(res)
        if yuan_5s is None:
            continue
        per_sec = float(yuan_5s) / VIDEO_RATE_SAMPLE_SECONDS
        parts.append(f"{res} ¥{per_sec:.2f}/秒")
    return " · ".join(parts)


def charge_fen_official_video(
    seconds: float,
    settings: Settings,
    *,
    model: str = "",
    resolution: str = "",
) -> int:
    """视频预估：按模型×清晰度结算参考秒价，不用 TokenFree 占位 37.5。"""
    from app.services.billing.pricing import charge_fen_for_tokens

    secs = max(float(seconds or 0), 2.0)
    raw = (model or getattr(settings, "model_video", "") or "seedance-2-5").strip()
    res = normalize_video_resolution(resolution, settings)
    # MiniMax 必须在 video_catalog_id 之前，否则会误落到 seedance-2-5
    if _is_minimax_video_model(raw):
        rate = vendor_video_yuan_per_sec(raw, res, settings)
    else:
        mid = video_catalog_id(raw)
        rate = vendor_video_yuan_per_sec(mid, res, settings)
    if rate is not None:
        return _markup_charge(max(1, int(math.ceil(secs * rate * 100))), settings)
    mult = VIDEO_RESOLUTION_MULT[res]
    tok = int(secs * settings.billing_est_seedance_tokens_per_sec * mult)
    _, charge = charge_fen_for_tokens(tok, "seedance2:video0", settings=settings)
    return charge


def build_official_rate_rows(
    rates: dict[str, OfficialRate],
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    """管理端推荐模型费率表（含用户价）。"""
    s = settings or get_settings()
    usd_cny = usd_cny_rate(s)
    items: list[dict[str, Any]] = []
    for spec in RECOMMENDED_MODELS:
        rate = lookup_rate(str(spec["id"]), rates)
        official_yuan = 0.0
        basis = "missing"
        rate_label = "TokenFree 价目未收录，请到控制台核对"
        if spec["capability"] == "video":
            hint = format_video_pricing_hint(str(spec["id"]))
            tiers = VENDOR_VIDEO_YUAN_5S_BY_RES.get(str(spec["id"]))
            if hint and tiers and "480p" in tiers:
                official_yuan = round(float(tiers["480p"]), 4)
                basis = "vendor_sec"
                listed = ""
                if rate and rate.placeholder:
                    listed = f"；TokenFree 表 model_ratio={rate.model_ratio} 疑似占位"
                rate_label = f"结算参考 {hint}{listed}"
        elif spec["capability"] == "image" and (
            "sunburst" in str(spec["id"]).lower() or "gpt-image" in str(spec["id"]).lower()
        ):
            from app.services.billing.pricing import kie_fen_per_credit

            credits = kie_sunburst_credits_for_size("2K")
            fen = max(1, int(round(credits * kie_fen_per_credit(s))))
            official_yuan = round(fen / 100.0, 4)
            basis = "kie_sunburst"
            rate_label = (
                f"Kie sunburst 2K {credits} 积分 ≈ ¥{official_yuan:.2f}"
                f"（1K {KIE_SUNBURST_CREDITS_1K} / 4K {KIE_SUNBURST_CREDITS_4K} 积分）"
            )
        elif rate and rate.billing == "per_call":
            official_yuan = rate.cny_per_call
            basis = "per_call"
            rate_label = f"TokenFree ${rate.usd_per_call:.4f}/次 ≈ ¥{official_yuan:.4f}"
        elif rate and rate.billing == "token":
            official_yuan = rate.cny_out_per_1m
            basis = "token"
            rate_label = f"TokenFree 输入 ¥{rate.cny_in_per_1m:.4f} / 输出 ¥{rate.cny_out_per_1m:.4f} 每百万"
        items.append(
            {
                "id": spec["id"],
                "label": spec["label"],
                "provider": "tokenfree",
                "capability": spec["capability"],
                "recommended": bool(spec["recommended"]),
                "note": spec["note"],
                "basis": basis,
                "rate_label": rate_label,
                "official_cost_yuan": official_yuan,
                "user_charge_yuan": official_yuan,
                "placeholder": bool(rate.placeholder) if rate else False,
                "markup": 1.0,
                "usd_cny": usd_cny,
                "verify_url": TOKENFREE_CONSOLE_URL,
            }
        )
    return items


def media_model_pricing_hint(
    model_id: str,
    *,
    capability: str | None = None,
    rates: dict[str, OfficialRate] | None = None,
    settings: Settings | None = None,
) -> str:
    """前台模型卡片资费短句；有结算参考或价目则生成，否则空串交给预设文案。"""
    raw = (model_id or "").strip()
    if not raw:
        return ""
    s = settings or get_settings()
    table = rates if rates is not None else cached_rates()
    from app.services.media_model_presets import resolve_preset_alias

    key = resolve_preset_alias(raw) or raw
    low = key.lower()

    # Seedance / MiniMax：多清晰度结算参考；禁止 MiniMax 回退成 seedance-2-5
    if "seedance" in low or _is_minimax_video_model(key):
        hint = format_video_pricing_hint(key)
        if hint:
            return hint

    if "gpt-image" in low or "sunburst" in low:
        from app.services.billing.pricing import kie_fen_per_credit

        credits = kie_sunburst_credits_for_size("2K")
        fen = max(1, int(round(credits * kie_fen_per_credit(s))))
        return f"约 ¥{fen / 100.0:.2f}/张 · 2K 参考"

    rate = lookup_rate(key, table) or lookup_rate(raw, table)
    if rate and rate.billing == "per_call" and rate.cny_per_call > 0:
        return f"约 ¥{rate.cny_per_call:.2f}/次"
    if rate and rate.billing == "token" and (rate.cny_in_per_1m > 0 or rate.cny_out_per_1m > 0):
        return f"按 Token 计费"
    return ""


async def fetch_tokenfree_pricing() -> dict[str, Any]:
    """GET TokenFree 公开价目，无需 API Key。"""
    url = tokenfree_pricing_url()
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(url)
    except httpx.HTTPError as exc:
        raise RuntimeError(f"TokenFree pricing 网络失败: {exc}") from exc
    if resp.status_code >= 400:
        raise RuntimeError(f"TokenFree pricing HTTP {resp.status_code}: {resp.text[:300]}")
    try:
        payload = resp.json()
    except ValueError as exc:
        raise RuntimeError("TokenFree 价目返回非 JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("TokenFree 价目格式异常")
    return payload


async def ensure_official_rates(settings: Settings | None = None) -> dict[str, OfficialRate]:
    """有缓存且未过期则复用；失败写短 TTL，预扣不因外网挂掉。"""
    ttl = _FAIL_TTL_SEC if _cache_failed else _CACHE_TTL_SEC
    if _cache is not None and _cache_at and (time.monotonic() - _cache_at) < ttl:
        return _cache
    try:
        payload = await fetch_tokenfree_pricing()
        parsed = parse_pricing_payload(payload, settings)
        if parsed:
            set_cached_rates(parsed)
            return parsed
        _mark_fetch_failed()
    except (RuntimeError, ValueError, TypeError) as exc:
        logger.info("tokenfree pricing skipped: %s", exc)
        _mark_fetch_failed()
    return cached_rates()


async def billing_official_rate_rows(settings: Settings | None = None) -> list[dict[str, Any]]:
    """拉取（或复用）官方价后生成推荐模型费率表。"""
    s = settings or get_settings()
    rates = await ensure_official_rates(s)
    return build_official_rate_rows(rates, s)
