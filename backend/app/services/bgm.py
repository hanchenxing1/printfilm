"""Project-level BGM resolution for FFmpeg compose."""

from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_STATIC_ROOT = Path(__file__).resolve().parents[2] / "static"
SHOT_BGM_MAX = 64

# Map mood keywords → filename stems under static/bgm/
_BGM_FILES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"紧张|悬疑|压迫"), "tense"),
    (re.compile(r"温暖|人文|故事"), "warm"),
    (re.compile(r"赛博|电子|科技"), "tech"),
    (re.compile(r"史诗|宏大|奇幻"), "epic"),
    (re.compile(r"轻快|专业|开源|产品|工作"), "upbeat"),
    (re.compile(r"冷静|纪实"), "calm"),
]


def clip_shot_bgm(mood: str | None) -> str:
    """Shot.bgm_mood 列上限 64，写入前截断。"""
    text = (mood or "").strip()
    return (text[:SHOT_BGM_MAX] if text else "neutral") or "neutral"


def resolve_bgm_path(mood: str | None) -> Path | None:
    """有本地曲库才叠 BGM；没有真实音频文件就跳过，避免正弦波垫乐当杂音。"""
    root = _STATIC_ROOT / "bgm"
    blob = (mood or "").strip()
    stem = "default"
    for pattern, name in _BGM_FILES:
        if pattern.search(blob):
            stem = name
            break
    for candidate in (
        root / f"{stem}.mp3",
        root / f"{stem}.m4a",
        root / f"{stem}.wav",
        root / "default.mp3",
        root / "default.m4a",
        root / "default.wav",
    ):
        if candidate.is_file():
            return candidate
    for ext in ("*.mp3", "*.m4a", "*.wav", "*.aac"):
        found = sorted(root.glob(ext))
        if found:
            return found[0]
    logger.debug("No BGM file under %s for mood=%s; skip BGM", root, mood)
    return None
