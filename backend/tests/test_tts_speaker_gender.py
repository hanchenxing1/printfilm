"""TTS speaker → edge-tts 性别映射（修复 zh_female_* 误判为男声）。"""

from app.services.voices import edge_tts_voice_for_speaker, infer_speaker_gender


def test_infer_speaker_gender_female_prefix():
    assert infer_speaker_gender("zh_female_xiaohe_uranus_bigtts") == "female"
    assert infer_speaker_gender("zh_female_cancan_uranus_bigtts") == "female"


def test_infer_speaker_gender_male_prefix():
    assert infer_speaker_gender("zh_male_shaonianzixin_uranus_bigtts") == "male"


def test_edge_voice_xiaohe_is_female_neural():
    assert edge_tts_voice_for_speaker("zh_female_xiaohe_uranus_bigtts") == "zh-CN-XiaoxiaoNeural"


def test_edge_voice_male_preset():
    assert edge_tts_voice_for_speaker("zh_male_shaonianzixin_uranus_bigtts") == "zh-CN-YunxiNeural"


def test_edge_voice_male_presets_are_not_all_yunxi():
    voices = {
        edge_tts_voice_for_speaker("zh_male_shaonianzixin_uranus_bigtts"),
        edge_tts_voice_for_speaker("zh_male_m191_uranus_bigtts"),
        edge_tts_voice_for_speaker("zh_male_baqiqingshu_uranus_bigtts"),
        edge_tts_voice_for_speaker("zh_male_taocheng_uranus_bigtts"),
    }
    assert len(voices) >= 3
    assert "zh-CN-YunyangNeural" in voices
    assert "zh-CN-YunxiaNeural" not in voices
