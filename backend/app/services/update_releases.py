# -*- coding: utf-8 -*-
"""客户端更新清单服务：读取/更新 data/update_releases.json。

清单结构（JSON）::

    {
      "desktop": {"version": "1.1.0", "version_code": 2, "url": "https://.../apps/xxx.exe",
                  "notes": "...", "force": false, "size": 0, "published_at": "2026-10-06T22:00:00"},
      "mobile":  {"version": "1.0.1", "version_code": 2, "url": "https://.../apps/xxx.apk",
                  "notes": "...", "force": false, "size": 0, "published_at": "..."},
      "history": [ {"platform": "desktop", "version": "1.1.0", "url": "...", "published_at": "..."} ]
    }

双端启动时调 GET /api/update/check 拿当前平台最新条目，与本机版本比对后决定是否弹窗提示更新。
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parents[2]          # backend 根目录
MANIFEST_PATH = BASE_DIR / "data" / "update_releases.json"

# 默认空清单（文件不存在时兜底）
_EMPTY: dict[str, Any] = {"desktop": {}, "mobile": {}, "history": []}


def _load() -> dict[str, Any]:
    if MANIFEST_PATH.exists():
        try:
            data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("desktop", {})
                data.setdefault("mobile", {})
                data.setdefault("history", [])
                return data
        except Exception:  # noqa: BLE001
            logger.warning("update_releases.json 解析失败，按空清单处理: %s", MANIFEST_PATH)
    return json.loads(json.dumps(_EMPTY))


def _save(data: dict[str, Any]) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_latest(platform: str) -> dict[str, Any]:
    """取某平台最新条目；无则返回 {}。"""
    return _load().get(platform) or {}


def all_releases() -> dict[str, Any]:
    return _load()


def semver_tuple(v: str) -> tuple:
    """把 '1.2.3' / '1.2' / '1' 解析成可比较的整数元组（不足位补 0）。"""
    parts = (v or "").strip().split(".")
    out = []
    for p in parts:
        digits = "".join(ch for ch in p if ch.isdigit())
        out.append(int(digits) if digits else 0)
    while len(out) < 3:
        out.append(0)
    return tuple(out[:3])


def is_newer(latest_version: str, current_version: str) -> bool:
    return semver_tuple(latest_version) > semver_tuple(current_version)


def upsert_release(
    platform: str,
    *,
    version: str,
    url: str,
    notes: str = "",
    force: bool = False,
    version_code: int | None = None,
    size: int | None = None,
) -> dict[str, Any]:
    """写入/更新某平台最新条目；追加一条 history。返回该平台条目。"""
    if platform not in ("desktop", "mobile"):
        raise ValueError(f"platform 必须是 desktop 或 mobile，收到 {platform!r}")
    if not version:
        raise ValueError("version 不能为空")
    if not url:
        raise ValueError("url 不能为空")

    data = _load()
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    entry: dict[str, Any] = {
        "version": version,
        "url": url,
        "notes": notes,
        "force": bool(force),
        "published_at": now,
    }
    if version_code is not None:
        entry["version_code"] = int(version_code)
    if size is not None:
        entry["size"] = int(size)

    data[platform] = entry
    history = data.setdefault("history", [])
    history.insert(0, {"platform": platform, "version": version, "url": url, "published_at": now})
    # 历史最多保留 50 条，避免无限增长
    data["history"] = history[:50]
    _save(data)
    logger.info("update_releases upsert platform=%s version=%s url=%s", platform, version, url)
    return entry
