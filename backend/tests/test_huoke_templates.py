"""获客科普模板：四平台结构 + 不编造体验铁律。"""

from types import SimpleNamespace

from app.services.ark import storyboard_name_policy
from app.services.style_lock import template_allow_source_names, template_shot_range
from app.services.templates_seed import TEMPLATES
from app.services.templates_seed_huoke import HUOKE_IRON_RULES, HUOKE_TEMPLATES

HUOKE_IDS = (
    "huoke_douyin_hook",
    "huoke_xhs_recommend",
    "huoke_review_facts",
    "huoke_soft_invite",
)


def test_huoke_templates_registered_in_seed():
    by_id = {t["id"]: t for t in TEMPLATES}
    for tid in HUOKE_IDS:
        assert tid in by_id, tid
        item = by_id[tid]
        assert item["category"][0] == "科普"
        assert "获客" in item["category"]
        assert "商业" in item["category"]
        assert item["llm_system_addon"].startswith(HUOKE_IRON_RULES)
        assert "店名" in item["llm_system_addon"]
        assert item["preview_cover"].endswith(f"{tid}.png")
        cfg = item["seedream_config"]
        assert cfg.get("photoreal") is True
        assert cfg.get("allow_source_names") is True
        assert cfg.get("consistency_mode") == "style"
        assert cfg.get("shot_count_min") >= 2
        assert cfg["shot_count_max"] >= cfg["shot_count_min"]


def test_huoke_platform_structures_are_distinct():
    addons = {t["id"]: t["llm_system_addon"] for t in HUOKE_TEMPLATES}
    assert "0-3秒钩子" in addons["huoke_douyin_hook"]
    assert "第一印象" in addons["huoke_xhs_recommend"]
    assert "性价比" in addons["huoke_review_facts"]
    assert "轻推荐" in addons["huoke_soft_invite"]
    assert "必须 4 镜" not in addons["huoke_douyin_hook"]
    assert addons["huoke_douyin_hook"] != addons["huoke_xhs_recommend"]


def test_huoke_shot_range_and_names_wire_into_pipeline_helpers():
    tpl = SimpleNamespace(seedream_config=HUOKE_TEMPLATES[0]["seedream_config"])
    assert template_shot_range(tpl) == (3, 4)
    assert template_allow_source_names(tpl) is True
    assert template_shot_range(SimpleNamespace(seedream_config={})) is None
    assert "原样保留" in storyboard_name_policy(True)
    assert "改用泛称" in storyboard_name_policy(False)


def test_template_ids_unique():
    ids = [t["id"] for t in TEMPLATES]
    assert len(ids) == len(set(ids))
