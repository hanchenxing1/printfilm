"""整集分镜预算：合并过碎草稿。"""

from app.services.drama.fragment_budget import (
    cap_llm_fragment_items,
    draft_duration_sec,
    merge_fragment_drafts,
    trim_episode_fragment_drafts,
)
from app.services.drama.build_fragments import EPISODE_DURATION_BUDGET_SEC, EPISODE_FRAGMENT_MAX


def _draft(content: str, *, duration: int | None = None, scene: str | None = None) -> dict:
    dur = duration if duration is not None else draft_duration_sec({"content": content})
    return {
        "content": content,
        "duration_sec": dur,
        "asset_ids": [],
        "scene_name": scene,
        "character_names": [],
    }


def test_trim_merges_down_to_max_count():
    drafts = [
        _draft(f"@duration:8\n镜{i}内容。", scene="教室")
        for i in range(15)
    ]
    trimmed = trim_episode_fragment_drafts(drafts)
    assert len(trimmed) <= EPISODE_FRAGMENT_MAX
    assert sum(draft_duration_sec(d) for d in trimmed) <= EPISODE_DURATION_BUDGET_SEC + 15


def test_trim_prefers_same_scene_neighbors():
    drafts = [
        _draft("@duration:6\nA对白。", scene="教室"),
        _draft("@duration:6\nB对白。", scene="教室"),
        _draft("@duration:6\nC对白。", scene="操场"),
        _draft("@duration:6\nD对白。", scene="操场"),
    ]
    trimmed = trim_episode_fragment_drafts(drafts, max_count=2, max_total_sec=999)
    assert len(trimmed) == 2
    assert "A对白" in trimmed[0]["content"]
    assert "B对白" in trimmed[0]["content"]


def test_merge_keeps_per_block_duration_tags():
    a = _draft("【BGM：轻】\n@duration:4\nA对白。", duration=4)
    b = _draft("@duration:6\nB对白。", duration=6)
    merged = merge_fragment_drafts(a, b)
    assert merged["content"].count("@duration:") == 2
    assert draft_duration_sec(merged) == 10
    assert merged["content"].index("@duration:4") < merged["content"].index("A对白")
    assert merged["content"].index("@duration:6") < merged["content"].index("B对白")


def test_merge_compress_scales_blocks_not_single_tag():
    a = _draft("@duration:8\nA。", duration=8)
    b = _draft("@duration:7\nB。", duration=7)
    merged = merge_fragment_drafts(a, b, compress=True)
    assert merged["content"].count("@duration:") == 2
    assert draft_duration_sec(merged) == 8


def test_cap_llm_fragment_items_merges_lines():
    items = [
        {"duration_sec": 6, "lines": ["第一句。"], "scene_name": "场1"},
        {"duration_sec": 6, "lines": ["第二句。"], "scene_name": "场1"},
        {"duration_sec": 6, "lines": ["第三句。"], "scene_name": "场1"},
        {"duration_sec": 6, "lines": ["第四句。"], "scene_name": "场2"},
        {"duration_sec": 6, "lines": ["第五句。"], "scene_name": "场2"},
    ]
    capped = cap_llm_fragment_items(items, max_items=3)
    assert len(capped) == 3
    assert len(capped[-1]["lines"]) >= 2
