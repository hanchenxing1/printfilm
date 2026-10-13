# -*- coding: utf-8 -*-
"""单机版 Agnes API Key 本地存取（data/agnes_keys.json）。

用户通过 设置页 保存/更新/删除 key；agnes_client._keys_from_settings 与
llm 路由在缺少 settings.agnes_api_keys 时回读本文件。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _key_file() -> Path:
    from app.config import data_dir_path

    return data_dir_path() / "agnes_keys.json"


def load_keys() -> list[str]:
    """返回用户保存的 Agnes key 列表（去重、去空）。"""
    f = _key_file()
    if not f.exists():
        return []
    try:
        data: Any = json.loads(f.read_text(encoding="utf-8"))
        keys = data.get("keys", []) if isinstance(data, dict) else data
        out: list[str] = []
        seen: set[str] = set()
        for k in keys or []:
            k = str(k or "").strip()
            if k and k not in seen:
                seen.add(k)
                out.append(k)
        return out
    except Exception:  # noqa: BLE001
        logger.warning("agnes_keys.json 解析失败: %s", f)
        return []


def save_keys(keys: list[str]) -> list[str]:
    """保存 key 列表（去重、去空）到本地文件，返回保存结果。"""
    out: list[str] = []
    seen: set[str] = set()
    for k in keys or []:
        k = str(k or "").strip()
        if k and k not in seen:
            seen.add(k)
            out.append(k)
    f = _key_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"keys": out}, ensure_ascii=False, indent=2), encoding="utf-8")
    # 让 agnes_client 单例感知新 key
    try:
        from app.services.agnes_client import reset_agnes_client

        reset_agnes_client()
    except Exception:  # noqa: BLE001
        pass
    return out


def key_status() -> dict[str, Any]:
    keys = load_keys()
    return {
        "configured": bool(keys),
        "count": len(keys),
        # 脱敏：只显示首尾 4 位
        "masked": [f"{k[:4]}…{k[-4:]}" if len(k) > 12 else "***" for k in keys],
    }
