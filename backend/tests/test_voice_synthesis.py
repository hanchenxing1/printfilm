"""漫剧音色 speaker 推断与试听文案测试。"""

from app.services.drama.voice_synthesis import (
    build_voice_sample_line_short,
    build_voice_sample_text,
    normalize_character_name,
)
from app.services.ark import ArkGateway
from app.services.voices import infer_drama_speaker_from_prompt, infer_speaker_gender


def test_normalize_character_name_strips_suffix() -> None:
    assert normalize_character_name("禹音色") == "禹"
    assert normalize_character_name("伯益") == "伯益"


def test_build_voice_sample_line_short() -> None:
    # 试听句须 ≥2s，固定句在自我介绍后追加声线说明（voice_synthesis.py）
    assert build_voice_sample_line_short("禹") == (
        "你好，我是禹。请听我的语气与声线，之后我会用这样的声音来讲述故事。"
    )
    assert build_voice_sample_line_short("很长的角色名称测试") == (
        "你好，我是很长的角色名称测。请听我的语气与声线，之后我会用这样的声音来讲述故事。"
    )


def test_build_voice_sample_text_short_mode() -> None:
    assert build_voice_sample_text("任意描述", "伯益", short=True) == (
        "你好，我是伯益。请听我的语气与声线，之后我会用这样的声音来讲述故事。"
    )


def test_infer_drama_speaker_screenshot_cast_differs() -> None:
    """词源爷爷/GBE/小胖/剪影/阿词 不能再全员落到同一条少年音。"""
    gbe = infer_drama_speaker_from_prompt(
        "神圣与委屈交织的萌系精灵音色，完全体为成年男性管风琴共鸣声线，"
        "低沉恢弘带悲悯感，语速庄重缓慢；压缩态转为高亮童声质感",
        character_name="GBE",
        asset_id=1,
    )
    xiaopang = infer_drama_speaker_from_prompt(
        "12岁男孩，童声偏圆润饱满，音域中等偏亮，自带憨厚的鼻音质感。",
        character_name="小胖",
        asset_id=2,
    )
    grandpa = infer_drama_speaker_from_prompt(
        "严厉下的天真知识狂魔，孤独感与热切感交织，半秒间完成肃穆到雀跃的变调。",
        character_name="词源爷爷",
        asset_id=3,
    )
    silhouette = infer_drama_speaker_from_prompt(
        "青年男声，二十五岁上下，声线偏冷偏低沉，尾音略带颗粒感与克制感。",
        character_name="人物剪影",
        asset_id=4,
    )
    aci = infer_drama_speaker_from_prompt(
        "12岁少年音，清亮偏高的声线带着青春期变声前的透亮质感。",
        character_name="阿词",
        asset_id=5,
    )
    speakers = {gbe, xiaopang, grandpa, silhouette, aci}
    assert len(speakers) == 5
    assert grandpa == "zh_male_baqiqingshu_uranus_bigtts"
    assert aci == "zh_male_shaonianzixin_uranus_bigtts"
    assert xiaopang == "zh_male_taocheng_uranus_bigtts"
    assert gbe == "zh_male_m191_uranus_bigtts"
    assert silhouette == "zh_male_ruyayichen_uranus_bigtts"


def test_infer_drama_speaker_youth_fallback_not_uncle() -> None:
    """默认「青年男声…语速沉稳」不能再落到霸气青叔。"""
    speaker = infer_drama_speaker_from_prompt(
        "青年男声，吐字清晰，语速沉稳",
        character_name="路人甲",
        asset_id=11,
    )
    assert speaker == "zh_male_taocheng_uranus_bigtts"


def test_infer_drama_speaker_shao_ye_not_grandpa() -> None:
    speaker = infer_drama_speaker_from_prompt(
        "青年声线，吐字清晰",
        character_name="少爷",
        asset_id=12,
    )
    assert infer_speaker_gender(speaker) == "male"
    assert speaker != "zh_male_baqiqingshu_uranus_bigtts"


def test_infer_drama_speaker_differs_by_role() -> None:
    yu = infer_drama_speaker_from_prompt(
        "中年男性，治水领袖，声线浑厚庄重",
        character_name="禹",
        asset_id=1,
    )
    boyi = infer_drama_speaker_from_prompt(
        "青年男性，儒雅谋士，声线清朗温和",
        character_name="伯益",
        asset_id=2,
    )
    elder = infer_drama_speaker_from_prompt(
        "老年男性，部落族老，声线沙哑沉稳",
        character_name="部落族老",
        asset_id=3,
    )
    assert yu != boyi or yu != elder
    assert all(s.startswith("zh_") for s in (yu, boyi, elder))


def test_build_voice_sample_text_uses_role_lines() -> None:
    yu = build_voice_sample_text("治水领袖，浑厚男声", "禹", short=False)
    crowd = build_voice_sample_text("百姓群像，朴实女声", "两岸百姓", short=False)
    assert "禹" in yu
    assert "两岸百姓" in crowd
    assert yu != crowd


def test_build_tts_additions_includes_context_texts() -> None:
    raw = ArkGateway._build_tts_additions("zh_female_vv_uranus_bigtts", "清亮少女音")
    assert raw is not None
    assert "context_texts" in raw
    assert "清亮少女音" in raw


def test_build_tts_additions_speaker_clone() -> None:
    raw = ArkGateway._build_tts_additions("S_abc123", "低沉男声")
    assert raw is not None
    assert "model_type" in raw
    assert "context_texts" in raw

