"""科普成片字幕预设与后期 BGM 解析。"""

from app.services.bgm import clip_shot_bgm, resolve_bgm_path
from app.services.pipeline import _kepu_video_prompt, _merge_subtitle_preset
from app.services.seedance_segments import build_segment_script, SegmentBeat


def test_merge_subtitle_preset_standard_overrides_template():
    out = _merge_subtitle_preset({"caption_scale": 1.4, "position": "split"}, "standard")
    assert out["caption_scale"] == 1.25
    assert out["position"] == "top"


def test_merge_subtitle_preset_large_bumps_caption():
    out = _merge_subtitle_preset({"caption_scale": 1.1}, "large")
    assert out["caption_scale"] == 1.55


def test_merge_subtitle_preset_split_sets_position():
    out = _merge_subtitle_preset({"position": "top"}, "split")
    assert out["position"] == "split"


def test_merge_subtitle_preset_unknown_is_noop():
    src = {"caption_scale": 1.1, "position": "top"}
    assert _merge_subtitle_preset(src, "") == src
    assert _merge_subtitle_preset(src, "unknown") == src


def test_clip_shot_bgm_truncates_to_column():
    assert len(clip_shot_bgm("轻快专业，音量低于人声，还带一段超长补充说明" * 4)) == 64
    assert clip_shot_bgm("") == "neutral"


def test_kepu_video_prompt_forbids_burn_when_sfx_off():
    script = build_segment_script(
        [
            SegmentBeat(duration=4, kind="visual", text="过肩工位"),
            SegmentBeat(duration=6, kind="narration", text="恒星燃料耗尽就会坍缩"),
        ],
        bgm_mood="轻快专业",
    )
    prompt = _kepu_video_prompt(
        "【字幕：全程简体中文字幕，旁白逐句同步烧录】\n" + script,
        style_prefix="写实",
        motion_bias="",
        camera="",
        ambient_only=False,
    )
    assert "烧录简体中文字幕" not in prompt
    assert "禁止在画面内烧录字幕" in prompt
    assert "后期叠旁白字幕" in prompt or "后期完成" in prompt


def test_resolve_bgm_path_skips_without_library():
    """仓库没有配乐文件时不生成正弦波垫乐。"""
    path = resolve_bgm_path("轻快专业")
    assert path is None
