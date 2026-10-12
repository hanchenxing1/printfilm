"""单集生成上下文组装 + 正文增量 seed 去重/新建（纯函数，不调 LLM）。"""

from app.services.drama.agents import (
    build_single_episode_context,
    format_character_asset_names_line,
)
from app.services.drama.seed import (
    classify_episode_seed_ops,
    collect_episode_seed_names,
)


def test_build_single_episode_context_includes_titles_neighbors_and_cast():
    summary = {
        "episodeCount": 3,
        "storyType": "儿童科普",
        "oneLineStory": "月亮跟着走",
        "characters": [{"name": "小明", "roleType": "主角", "title": "好奇娃"}],
        "synopsis": "科普系列",
    }
    existing = [
        {
            "episodeNumber": 1,
            "title": "开篇",
            "creative": "第一集创意",
            "summary": "第一集摘要",
            "body": "### 场1-1\n日 内 教室\n出场人物：小明\n△ 小明抬头。\n小明（好奇）：月亮为什么跟着我？\n" * 5,
        },
        {
            "episodeNumber": 2,
            "title": "跟月",
            "creative": "第二集创意",
            "summary": "第二集摘要",
            "body": "",
        },
        {"episodeNumber": 3, "title": "视差", "creative": "", "summary": "", "body": ""},
    ]
    parts = build_single_episode_context(
        summary,
        existing,
        2,
        project_source="整剧：儿童看月亮",
        character_asset_names=["小明", "老师"],
    )
    joined = "\n\n".join(parts)
    assert "整剧：儿童看月亮" in joined
    assert "第 1 集：开篇" in joined
    assert "第 3 集：视差" in joined
    assert "邻集正文" in joined
    assert "场1-1" in joined
    assert "须优先使用这些定妆名：小明、老师" in joined
    assert "邻集创意/摘要补充" in joined
    assert "第二集" not in joined or "第 2 集" in joined  # 邻集不含本集正文块即可


def test_format_character_asset_names_line_empty():
    line = format_character_asset_names_line([])
    assert "暂无定妆角色资产" in line


def test_collect_episode_seed_names_from_cast_and_summary():
    summary = {
        "storyType": "都市",
        "characters": [{"name": "林晓", "roleType": "主角", "title": "记者"}],
    }
    body = (
        "### 场3-1\n"
        "夜 外 天台\n"
        "出场人物：林晓、陈默\n"
        "△ 两人站定。\n"
        "林晓（冷静）：你来晚了。\n"
        "### 场3-2\n"
        "日 内 咖啡店\n"
        "出场人物：陈默\n"
        "△ 陈默坐下。\n"
    )
    characters, scenes, by_name = collect_episode_seed_names(summary, body)
    assert "林晓" in characters
    assert "陈默" in characters
    assert "天台" in scenes
    assert "咖啡店" in scenes
    assert "林晓" in by_name


def test_classify_episode_seed_ops_reuse_and_create():
    existing = {("character", "林晓"), ("scene", "天台")}
    result = classify_episode_seed_ops(
        existing,
        character_names=["林晓", "陈默"],
        scene_names=["天台", "咖啡店"],
    )
    created_names = {(x["type"], x["name"]) for x in result.created}
    reused_names = {(x["type"], x["name"]) for x in result.reused}
    assert ("character", "陈默") in created_names
    assert ("scene", "咖啡店") in created_names
    assert ("character", "林晓") in reused_names
    assert ("scene", "天台") in reused_names
    assert result.created_count == 2
    assert result.reused_count == 2


def test_classify_skips_voice_like_character_names():
    result = classify_episode_seed_ops(
        set(),
        character_names=["旁白音色", "小明（声音）", "小红"],
        scene_names=[],
    )
    names = [x["name"] for x in result.created if x["type"] == "character"]
    assert names == ["小明", "小红"]
