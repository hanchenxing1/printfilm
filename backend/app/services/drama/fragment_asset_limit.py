"""每镜视觉资产上限：预留画风板与衔接帧后，避免一次提交超过参考图上限。"""

from __future__ import annotations

import re
from typing import Any

# 预留画风板 + 上一镜尾帧后，分镜可挂的角色/场景/道具
FRAGMENT_MAX_VISUAL_ASSETS = 6
FRAGMENT_MAX_CHARACTERS = 3
FRAGMENT_MAX_PROPS = 2

_ASSET_MENTION_RE = re.compile(r"@asset:(\d+)")


def cap_asset_id_list(asset_ids: list[int] | None, *, limit: int = FRAGMENT_MAX_VISUAL_ASSETS) -> list[int]:
    """保序去重截断（合并分镜后不再区分类型时用）。"""
    out: list[int] = []
    seen: set[int] = set()
    for raw in asset_ids or []:
        aid = int(raw or 0)
        if aid <= 0 or aid in seen:
            continue
        seen.add(aid)
        out.append(aid)
        if len(out) >= max(1, int(limit)):
            break
    return out


def cap_fragment_asset_ids(
    asset_ids: list[int],
    assets: list[Any],
    *,
    limit: int = FRAGMENT_MAX_VISUAL_ASSETS,
) -> list[int]:
    """每镜视觉参考：1 场景 + 最多 3 角色 + 剩余给道具。"""
    by_id = {int(getattr(item, "id", 0) or 0): item for item in assets if getattr(item, "id", None)}
    scenes: list[int] = []
    chars: list[int] = []
    props: list[int] = []
    other: list[int] = []
    seen: set[int] = set()
    for raw in asset_ids:
        aid = int(raw or 0)
        if aid <= 0 or aid in seen:
            continue
        seen.add(aid)
        kind = str(getattr(by_id.get(aid), "type", "") or "").strip().lower()
        if kind == "scene":
            scenes.append(aid)
        elif kind == "character":
            chars.append(aid)
        elif kind in {"prop", "material", "none"}:
            props.append(aid)
        else:
            other.append(aid)
    cap = max(1, int(limit))
    picked: list[int] = []
    if scenes:
        picked.append(scenes[0])
    remain = cap - len(picked)
    char_take = min(FRAGMENT_MAX_CHARACTERS, remain)
    picked.extend(chars[:char_take])
    remain = cap - len(picked)
    prop_take = min(FRAGMENT_MAX_PROPS, remain)
    picked.extend(props[:prop_take])
    remain = cap - len(picked)
    picked.extend(other[:remain])
    return picked


def strip_unlisted_asset_mentions(content: str, allowed_ids: list[int] | set[int]) -> str:
    """正文里只保留已入选的 @asset，避免生成阶段再把砍掉的资产捞回来。"""
    allowed = {int(x) for x in allowed_ids if int(x) > 0}

    def _keep(match: re.Match[str]) -> str:
        aid = int(match.group(1))
        return match.group(0) if aid in allowed else ""

    cleaned = _ASSET_MENTION_RE.sub(_keep, content or "")
    return re.sub(r"[ \t]{2,}", " ", cleaned).strip()
