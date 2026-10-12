# -*- coding: utf-8 -*-
"""从上游渠道拉取可用模型目录（TokenFree / OpenAI 兼容）。"""
from __future__ import annotations

import logging
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.model_routing_config import infer_model_capability, normalize_model_name
from app.services.tokenfree_gateway import TOKENFREE_BASE_URL

logger = logging.getLogger(__name__)


def _model_id(item: dict[str, Any]) -> str:
    for key in ("id", "name", "model"):
        raw = item.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return ""


async def _resolve_channel_credentials(
    db: AsyncSession | None,
    *,
    channel_id: str | None,
    protocol: str,
    base_url: str,
    api_key_override: str | None,
) -> tuple[str, str, str]:
    """返回 (protocol, base_url, api_key)。"""
    proto = (protocol or "auto").strip().lower() or "auto"
    base = (base_url or "").strip().rstrip("/")
    key = (api_key_override or "").strip()

    if db is not None and channel_id:
        from app.services.model_settings import _load_channels

        channels = await _load_channels(db, runtime=True)
        channel = next((item for item in channels if item.id == channel_id), None)
        if channel is not None:
            if not key:
                key = (channel.api_key or "").strip()
            if not base:
                base = (channel.base_url or "").strip().rstrip("/")
            if proto in {"", "auto"}:
                proto = (channel.protocol or "auto").strip().lower() or "auto"

    if proto == "ark" and not base:
        base = TOKENFREE_BASE_URL.rstrip("/")
    if proto == "kie" and not base:
        base = TOKENFREE_BASE_URL.rstrip("/")
    return proto, base, key


async def _list_openai_compatible_models(
    *,
    base_url: str,
    api_key: str,
    capability: str = "all",
) -> list[dict[str, str]]:
    """GET {base}/models，按 OpenAI 兼容响应解析；能力优先 TokenFree /api/pricing。"""
    if not base_url:
        raise RuntimeError("请先填写 Base URL")
    if not api_key:
        raise RuntimeError("请先填写 API Key，或使用已保存密钥的渠道")

    # 价目含 tags / supported_endpoint_types，供 infer_model_capability 使用
    try:
        from app.services.tokenfree_pricing import ensure_official_rates

        await ensure_official_rates()
    except Exception:  # noqa: BLE001
        logger.info("TokenFree 价目预热失败，模型能力回退名字规则", exc_info=True)

    headers = {"Authorization": f"Bearer {api_key}"}
    url = f"{base_url.rstrip('/')}/models"
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.get(url, headers=headers)
        if resp.status_code >= 400:
            raise RuntimeError(f"拉取模型目录失败 HTTP {resp.status_code}: {resp.text[:300]}")
        payload = resp.json()

    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        raise RuntimeError("上游返回格式异常：缺少 data 列表")

    cap_filter = (capability or "all").strip().lower()
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in data:
        if not isinstance(item, dict):
            continue
        model_id = _model_id(item)
        if not model_id:
            continue
        # 列表项偶发自带 tags / endpoints 时优先用；否则走价目缓存 + 名字规则
        item_cap = None
        try:
            from app.services.tokenfree_pricing import capability_from_tokenfree_meta

            raw_eps = item.get("supported_endpoint_types") or item.get("endpoints") or []
            eps = raw_eps if isinstance(raw_eps, list) else []
            item_cap = capability_from_tokenfree_meta(str(item.get("tags") or ""), eps)
        except Exception:  # noqa: BLE001
            item_cap = None
        cap = item_cap or infer_model_capability(model_id)
        if cap_filter not in {"", "all"} and cap != cap_filter:
            continue
        key = normalize_model_name(model_id)
        if key in seen:
            continue
        seen.add(key)
        label = str(item.get("display_name") or model_id)
        out.append({"id": model_id, "label": label if label else model_id, "capability": cap})
    out.sort(key=lambda row: row["id"])
    return out


async def list_upstream_models(
    db: AsyncSession | None = None,
    *,
    channel_id: str | None = None,
    protocol: str = "auto",
    base_url: str = "",
    api_key_override: str | None = None,
    capability: str = "all",
) -> list[dict[str, str]]:
    """按渠道协议拉取可用模型。"""
    proto, base, key = await _resolve_channel_credentials(
        db,
        channel_id=channel_id,
        protocol=protocol,
        base_url=base_url,
        api_key_override=api_key_override,
    )

    if proto == "volc_tts":
        raise RuntimeError("豆包 TTS 暂不支持从上游拉取模型目录，请手动填写 speaker / 音色 ID")

    if proto == "kie" or proto == "ark" or "volces.com" in base.lower() or "kie.ai" in base.lower():
        from app.services.tokenfree_gateway import TOKENFREE_BASE_URL, resolve_tokenfree_api_key

        base = TOKENFREE_BASE_URL
        key = key or resolve_tokenfree_api_key()
        return await _list_openai_compatible_models(
            base_url=base,
            api_key=key,
            capability=capability,
        )

    if not base:
        from app.services.tokenfree_gateway import TOKENFREE_BASE_URL

        base = TOKENFREE_BASE_URL

    return await _list_openai_compatible_models(
        base_url=base,
        api_key=key,
        capability=capability,
    )
