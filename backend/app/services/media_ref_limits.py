"""TokenFree 视频参考图张数上限（与漫剧分镜资产规则解耦）。"""

from __future__ import annotations

# 下游插件硬上限：一次提交最多 9 张参考图
MAX_REFERENCE_IMAGES = 9


def cap_url_list(urls: list[str] | None, *, limit: int = MAX_REFERENCE_IMAGES) -> list[str]:
    """去重并截到上游可上传张数。"""
    out: list[str] = []
    seen: set[str] = set()
    for raw in urls or []:
        url = str(raw or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(url)
        if len(out) >= max(1, int(limit)):
            break
    return out


def subject_image_budget(*, has_style_board: bool = False, has_continuity: bool = False) -> int:
    """主体参考图名额：总张数减去画风板与衔接尾帧。"""
    n = MAX_REFERENCE_IMAGES
    if has_style_board:
        n -= 1
    if has_continuity:
        n -= 1
    return max(1, n)
