"""提交 Seedance 前：名字不叠写、角色 VO 不进旁白、未开口不挂音色。"""

from app.services.drama.build_seedance_generate_body import (
    build_seedance_content_items,
    build_seedance_prompt_text,
    describe_seedance_content_slots,
)
from app.services.seedance_segments import (
    build_seedance_production_section,
    rewrite_misclassified_visual_voice_lines,
)


def _char(asset_id: int, name: str, *, audio: str | None = None) -> dict:
    params = {}
    if audio:
        params["voiceAudio"] = {"url": audio}
    return {
        "id": asset_id,
        "type": "character",
        "assetType": "image",
        "name": name,
        "cover": f"https://cdn.example.com/{name}.png",
        "url": "",
        "params": {**params, "entityName": name},
    }


def _scene(asset_id: int, name: str) -> dict:
    return {
        "id": asset_id,
        "type": "scene",
        "assetType": "image",
        "name": name,
        "cover": f"https://cdn.example.com/{name}.png",
        "url": "",
        "params": {"entityName": name},
    }


def _prop(asset_id: int, name: str) -> dict:
    return {
        "id": asset_id,
        "type": "prop",
        "assetType": "image",
        "name": name,
        "cover": f"https://cdn.example.com/{name}.png",
        "url": "",
        "params": {"entityName": name},
    }


# 对齐生产事故：第一镜正文已写名字又挂 @asset
_ACI_SCRIPT = """@duration:7 【配乐】｜木吉他轻快起步，渐弱
【场景】日 · 外 · 现代校门口街道（夕阳）@asset:4876
【画面·全景】放学人潮中，阿词@asset:4859 和小胖@asset:4860 并肩慢慢走。小胖抱着贴满贴纸的搬家纸箱@asset:4882 ，两人一路无话
【旁白】阿词（vo，低落）。
【旁白】阿词："明天，我最好的朋友小胖，就要搬去上海了。"
"""

_ACI_REFERENCE = [
    _scene(4876, "校门口"),
    _char(4859, "阿词", audio="https://cdn.example.com/aci.mp3"),
    _char(4860, "小胖", audio="https://cdn.example.com/pang.mp3"),
    _prop(4882, "搬家纸箱"),
]


def test_asset_mention_does_not_repeat_adjacent_name():
    prompt = build_seedance_prompt_text(_ACI_SCRIPT, _ACI_REFERENCE, burn_subtitles=False)
    assert "阿词阿词" not in prompt
    assert "小胖小胖" not in prompt
    assert "搬家纸箱搬家纸箱" not in prompt
    assert "阿词（参考图2）" in prompt
    assert "小胖（参考图3）" in prompt
    assert "搬家纸箱（参考图4）" in prompt
    assert "校门口（参考图1）" in prompt


def test_asset_mention_strips_name_after_token():
    script = "【画面】@asset:4876 校门口。"
    prompt = build_seedance_prompt_text(script, [_scene(4876, "校门口")], burn_subtitles=False)
    assert "校门口（参考图1） 校门口" not in prompt
    assert "校门口校门口" not in prompt
    assert "校门口（参考图1）" in prompt


def test_short_asset_name_does_not_eat_longer_name():
    script = "【画面】大禹@asset:1 站在河边。"
    prompt = build_seedance_prompt_text(script, [_char(1, "禹")], burn_subtitles=False)
    assert "大（参考图1）" not in prompt
    assert "大禹" in prompt


def test_os_stage_stays_inner_monologue():
    assert "内心独白" in rewrite_misclassified_visual_voice_lines("小宇（OS）：原来月亮是这样变化的。")
    assert "内心独白" in rewrite_misclassified_visual_voice_lines("【旁白】阿词（os，低落）。")
    closeup = rewrite_misclassified_visual_voice_lines("阿词（close-up）：站住。")
    assert "内心独白" not in closeup
    assert "【对白" in closeup


def test_unlabeled_speaker_skips_reference_audio():
    """对白仍改写成【对白】，但暂不把试听挂进 content。"""
    script = "@duration:6\n禹：水患未平。"
    reference = [_char(1, "禹", audio="https://cdn.example.com/yu.mp3")]
    items = build_seedance_content_items(script, reference, burn_subtitles=False)
    audios = [
        item["audio_url"]["url"]
        for item in items
        if item.get("type") == "audio_url"
    ]
    assert audios == []
    assert "【对白" in items[0]["text"]
    assert "【强制约束：角色音色】" not in items[0]["text"]


def test_character_vo_narration_becomes_dialogue_not_stage_direction():
    fixed = rewrite_misclassified_visual_voice_lines(_ACI_SCRIPT)
    assert "【旁白】阿词（vo，低落）" not in fixed
    assert "【画面" in fixed and "阿词（vo，低落）" in fixed
    assert "【对白" in fixed
    assert "明天，我最好的朋友小胖" in fixed
    assert "【旁白】阿词：" not in fixed
    section = build_seedance_production_section(fixed, burn_subtitles=False)
    assert "第三人称旁白" not in section
    assert "【对白" in section or "对白" in section


def test_true_third_person_narration_stays_narration():
    script = "@duration:4\n【画面】校门口\n【旁白】明天，小胖就要搬走了。"
    fixed = rewrite_misclassified_visual_voice_lines(script)
    assert "【旁白】明天，小胖就要搬走了。" in fixed
    assert "【对白" not in fixed


def test_bound_voice_not_submitted_as_reference_audio():
    """已绑定试听也不提交 reference_audio，口播交给模型。"""
    items = build_seedance_content_items(_ACI_SCRIPT, _ACI_REFERENCE, burn_subtitles=False)
    audios = [
        item["audio_url"]["url"]
        for item in items
        if item.get("type") == "audio_url"
    ]
    assert audios == []
    text = items[0]["text"]
    assert "【强制约束：角色音色】" not in text
    assert "参考音频" not in text
    labels = describe_seedance_content_slots(
        _ACI_REFERENCE,
        None,
        has_text=True,
        content=_ACI_SCRIPT,
    )
    assert not any("音色" in label for label in labels)


def test_peiyue_cue_feeds_production_bgm():
    section = build_seedance_production_section(_ACI_SCRIPT, burn_subtitles=False)
    assert "木吉他轻快起步，渐弱" in section
    assert "贴合内容的轻量配乐" not in section


def test_prop_locked_in_reference_section():
    prompt = build_seedance_prompt_text(_ACI_SCRIPT, _ACI_REFERENCE, burn_subtitles=False)
    assert "【强制约束：道具】" in prompt
    assert "搬家纸箱：参考图4" in prompt
