"""科普分镜：模板角色不当作用户强制；是否出人由 LLM 按模板与主题决定。"""

from types import SimpleNamespace

from app.services.pipeline import _effective_character_prompt, resolve_script_character_bible


def test_effective_character_prompt_ignores_template_fallback():
    tpl = SimpleNamespace(seedream_config={"character_prompt": "模板操作员必须出镜"})
    project = SimpleNamespace(character_prompt="", template=tpl)
    assert _effective_character_prompt(project) == ""


def test_effective_character_prompt_keeps_user_override():
    project = SimpleNamespace(character_prompt="  只出剪影人物  ", template=None)
    assert _effective_character_prompt(project) == "只出剪影人物"


def test_script_bible_prefers_user_then_llm():
    assert resolve_script_character_bible("用户人设", "LLM 人设") == "用户人设"
    assert resolve_script_character_bible("", "侧脸操作员，不锁同一张脸") == "侧脸操作员，不锁同一张脸"
    assert resolve_script_character_bible("", "") == "无固定人物，各镜独立场景"
