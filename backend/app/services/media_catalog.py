"""前台图/视频模型目录：来自 TokenFree 路由快照，不再展示 Kie/方舟。"""

from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.schemas_routing import DefaultModels, LogicalModel, LogicalModelCapability, SystemModelChannel
from app.services.model_routing_config import infer_model_capability, normalize_model_name


def _row(
    *,
    model_id: str,
    label: str,
    recommended: bool,
    description: str = "",
    capability: LogicalModelCapability | None = None,
) -> dict[str, Any]:
    """组装前台一条模型选项（含按模型参数白名单与展示文案）。"""
    from app.services.media_model_presets import preset_display_meta

    meta = preset_display_meta(model_id)
    friendly_label = (meta.get("label") or "").strip()
    # 原始 id / 别名当 label 时优先用预设友好名
    raw_label = (label or model_id).strip() or model_id
    if friendly_label and (
        not raw_label
        or normalize_model_name(raw_label) == normalize_model_name(model_id)
        or raw_label.lower() in {"seedance 2", "seedance 2.5", "seedance2", "seedance2.5"}
    ):
        display_label = friendly_label
    else:
        display_label = raw_label

    row: dict[str, Any] = {
        "id": model_id,
        "label": display_label,
        "description": (description or meta.get("note") or "").strip(),
        "pricing_hint": (meta.get("pricing_hint") or "").strip(),
        "eta_hint": (meta.get("eta_hint") or "").strip(),
        "provider": "tokenfree",
        "recommended": recommended,
    }

    # 前台只展示定性选用提示（清晰度/贵慢等），不用结算秒价覆盖

    from app.services.media_model_presets import model_generation_options

    opts = model_generation_options(model_id)
    if capability == "image" or opts.get("capability") == "image":
        if opts.get("allowed_aspect_ratios"):
            row["allowed_aspect_ratios"] = list(opts["allowed_aspect_ratios"])
        if opts.get("allowed_resolutions"):
            row["allowed_resolutions"] = list(opts["allowed_resolutions"])
    if capability == "video" or opts.get("capability") == "video":
        from app.services.seedance_resolutions import (
            allowed_video_resolutions,
            video_duration_bounds,
        )

        row["allowed_resolutions"] = allowed_video_resolutions(model_id)
        if opts.get("allowed_aspect_ratios"):
            row["allowed_aspect_ratios"] = list(opts["allowed_aspect_ratios"])
        lo, hi = video_duration_bounds(model_id)
        row["duration_min"] = lo
        row["duration_max"] = hi
    return row


def build_media_catalog(
    *,
    logical_models: list[LogicalModel],
    channels: list[SystemModelChannel],
    defaults: DefaultModels,
    fallback_image: str = "",
    fallback_video: str = "",
) -> dict[str, Any]:
    """按逻辑模型 + 渠道勾选生成 image/video 目录。

    友好别名（seedance-2 / seedance-2.5）归一到预设规范 id，避免列表重复；
    并保证文/图/视预设始终出现在目录中。
    """
    from app.services.media_model_presets import preset_ids, resolve_preset_alias

    images: list[dict[str, Any]] = []
    videos: list[dict[str, Any]] = []
    seen_image: set[str] = set()
    seen_video: set[str] = set()

    def _canon(mid: str) -> str:
        aliased = resolve_preset_alias(mid)
        return (aliased or mid).strip() or mid

    default_image = _canon((defaults.image_model or "").strip())
    default_video = _canon((defaults.video_model or "").strip())

    def _append(
        *,
        model_id: str,
        label: str,
        capability: LogicalModelCapability,
    ) -> None:
        mid = _canon(model_id)
        if not mid:
            return
        key = normalize_model_name(mid)
        if capability == "image":
            if key in seen_image:
                return
            seen_image.add(key)
            images.append(
                _row(
                    model_id=mid,
                    label=label,
                    recommended=normalize_model_name(mid) == normalize_model_name(default_image),
                    capability="image",
                )
            )
        elif capability == "video":
            if key in seen_video:
                return
            seen_video.add(key)
            videos.append(
                _row(
                    model_id=mid,
                    label=label,
                    recommended=normalize_model_name(mid) == normalize_model_name(default_video),
                    capability="video",
                )
            )

    # 先放全量预设，保证前台名称与档位一致（Seedance 2.0 / 2.0 Mini / 2.5 …）
    for mid in preset_ids("image"):
        _append(model_id=mid, label=mid, capability="image")
    for mid in preset_ids("video"):
        _append(model_id=mid, label=mid, capability="video")

    for model in logical_models:
        if not model.enabled:
            continue
        mid = (model.id or "").strip()
        if not mid:
            continue
        label = (model.name or mid).strip() or mid
        if model.capability == "image":
            _append(model_id=mid, label=label, capability="image")
        elif model.capability == "video":
            _append(model_id=mid, label=label, capability="video")

    for channel in channels:
        if not channel.enabled:
            continue
        for raw in channel.models:
            mid = (raw or "").strip()
            if not mid:
                continue
            cap = infer_model_capability(mid)
            if cap in {"image", "video"}:
                _append(model_id=mid, label=mid, capability=cap)  # type: ignore[arg-type]

    if not default_image:
        default_image = images[0]["id"] if images else _canon((fallback_image or "").strip())
    if not default_video:
        default_video = videos[0]["id"] if videos else _canon((fallback_video or "").strip())

    def _ensure_default_in_list(
        default_id: str,
        bucket: list[dict[str, Any]],
        *,
        capability: LogicalModelCapability,
    ) -> None:
        did = _canon(default_id)
        if not did:
            return
        norm = normalize_model_name(did)
        if any(normalize_model_name(str(row.get("id") or "")) == norm for row in bucket):
            return
        bucket.insert(
            0,
            _row(model_id=did, label=did, recommended=True, capability=capability),
        )

    _ensure_default_in_list(default_image, images, capability="image")
    _ensure_default_in_list(default_video, videos, capability="video")
    if not images and default_image:
        images.append(
            _row(
                model_id=default_image,
                label=default_image,
                recommended=True,
                capability="image",
            )
        )
    if not videos and default_video:
        videos.append(
            _row(
                model_id=default_video,
                label=default_video,
                recommended=True,
                capability="video",
            )
        )

    # 推荐标记以规范化默认 id 为准
    for row in images:
        row["recommended"] = normalize_model_name(str(row.get("id") or "")) == normalize_model_name(
            default_image
        )
    for row in videos:
        row["recommended"] = normalize_model_name(str(row.get("id") or "")) == normalize_model_name(
            default_video
        )

    return {
        "image_models": images,
        "video_models": videos,
        "defaults": {
            "image_model": default_image,
            "video_model": default_video,
        },
    }


def catalog_payload() -> dict[str, Any]:
    """公开目录 JSON，供前台 /api/media-models。"""
    from app.services.model_settings import get_routing_snapshot

    snap = get_routing_snapshot()
    settings = get_settings()
    return build_media_catalog(
        logical_models=list(snap.logical_models),
        channels=list(snap.channels),
        defaults=snap.default_models,
        fallback_image=settings.model_image,
        fallback_video=settings.model_video,
    )


def is_valid_project_media_model(model_id: str | None, capability: LogicalModelCapability) -> bool:
    """科普项目 image_model / video_model：与 /api/media-models 及 TokenFree 路由一致。"""
    mid = (model_id or "").strip()
    if not mid:
        return True
    from app.services.logical_model_router import resolve_logical_model_candidates

    cat = catalog_payload()
    list_key = "image_models" if capability == "image" else "video_models"
    norm_mid = normalize_model_name(mid)
    for row in cat.get(list_key) or []:
        if normalize_model_name(str(row.get("id") or "")) == norm_mid:
            return True
    defaults = cat.get("defaults") if isinstance(cat.get("defaults"), dict) else {}
    def_key = "image_model" if capability == "image" else "video_model"
    if normalize_model_name(str(defaults.get(def_key) or "")) == norm_mid:
        return True
    if resolve_logical_model_candidates(capability, mid):
        return True
    # 与前台 /api/media-models 同源；能力推断一致即允许保存，具体路由在生成阶段解析
    if infer_model_capability(mid) == capability:
        return True
    settings = get_settings()
    fallback = (settings.model_image if capability == "image" else settings.model_video) or ""
    if normalize_model_name(fallback) == norm_mid:
        return True
    return False
