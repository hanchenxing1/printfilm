"""站点预设模型与按模型参数白名单。"""

from __future__ import annotations

from app.services.media_model_presets import (
    all_preset_channel_models,
    clamp_default_to_preset,
    is_preset_model,
    model_generation_options,
    preset_ids,
)
from app.services.seedance_resolutions import (
    allowed_video_resolutions,
    clamp_video_duration,
    clamp_video_resolution,
    video_duration_bounds,
)


def test_all_preset_channel_models_covers_four_caps() -> None:
    models = all_preset_channel_models()
    assert "kimi-k2.6" in models
    assert "seedream-5-0-pro" in models
    assert "gpt-image-2" in models
    assert "seedance-2-5" in models
    assert "MiniMax-H3" in models
    assert "gemini-3.1-flash-tts" in models
    assert len(models) == sum(len(preset_ids(c)) for c in ("text", "image", "video", "audio"))


def test_clamp_default_audio_only_gemini() -> None:
    assert clamp_default_to_preset("audio", "qwen-tts-2025-05-22") == "gemini-3.1-flash-tts"
    assert clamp_default_to_preset("audio", "gemini-3.1-flash-tts") == "gemini-3.1-flash-tts"
    assert is_preset_model("audio", "gemini-3.1-flash-tts") is True
    assert is_preset_model("audio", "elevenlabs-tts") is False


def test_clamp_seedance_aliases_to_canonical() -> None:
    assert clamp_default_to_preset("video", "seedance-2.5") == "seedance-2-5"
    assert clamp_default_to_preset("video", "seedance-2") == "seedance-2-0"
    assert is_preset_model("video", "seedance-2.5") is True


def test_clamp_seedream_aliases_to_canonical() -> None:
    assert clamp_default_to_preset("image", "seedream-5.0") == "seedream-5-0-pro"
    assert clamp_default_to_preset("image", "seedream-5") == "seedream-5-0-pro"
    assert clamp_default_to_preset("image", "gpt-image-2-5") == "gpt-image-2"
    assert is_preset_model("image", "seedream-5.0") is True


def test_build_body_clamps_minimax_duration() -> None:
    """请求体组装时 MiniMax 时长不得超过 15。"""
    from app.services.drama.build_seedance_generate_body import build_seedance_generate_body

    body = build_seedance_generate_body(
        {
            "content": "测试镜头",
            "model_id": "MiniMax-H3",
            "duration_fallback": 30,
            "resolution": "1080p",
            "aspect_ratio": "9:16",
        }
    )
    assert body["duration"] == 15
    assert body["resolution"] == "720p"


def test_image_options_standard_1k_2k() -> None:
    for mid in ("seedream-5-0-pro", "gpt-image-2"):
        opts = model_generation_options(mid)
        assert opts["capability"] == "image"
        assert opts["allowed_resolutions"] == ["1K", "2K"]
        assert "3:4" in opts["allowed_aspect_ratios"]


def test_minimax_h3_video_options() -> None:
    opts = model_generation_options("MiniMax-H3")
    assert opts["capability"] == "video"
    assert opts["allowed_resolutions"] == ["720p"]
    assert opts["duration_min"] == 4
    assert opts["duration_max"] == 15
    assert allowed_video_resolutions("MiniMax-H3") == ["720p"]
    assert video_duration_bounds("MiniMax-H3") == (4, 15)
    assert clamp_video_duration("MiniMax-H3", 30) == 15
    assert clamp_video_duration("MiniMax-H3", 8) == 8
    assert clamp_video_resolution("MiniMax-H3", "1080p") == "720p"
    assert clamp_video_resolution("MiniMax-H3", "480p") == "720p"

def test_seedance_20_options_safe() -> None:
    opts = model_generation_options("seedance-2-0")
    assert opts["allowed_resolutions"] == ["480p", "720p"]
    assert opts["duration_max"] == 30
    opts25 = model_generation_options("seedance-2-5")
    assert opts25["allowed_resolutions"] == ["480p", "720p", "1080p"]


def test_seedance_mini_safe_resolutions() -> None:
    opts = model_generation_options("seedance-2-0-mini")
    assert opts["allowed_resolutions"] == ["480p", "720p"]
    assert opts["duration_max"] == 30


def test_catalog_image_row_has_allowed_params() -> None:
    from app.schemas_routing import DefaultModels, LogicalModel
    from app.services.media_catalog import build_media_catalog

    payload = build_media_catalog(
        logical_models=[
            LogicalModel(
                id="seedream-5-0-pro",
                name="Seedream 5",
                capability="image",
                enabled=True,
                bindings=[],
            ),
            LogicalModel(
                id="MiniMax-H3",
                name="MiniMax H3",
                capability="video",
                enabled=True,
                bindings=[],
            ),
        ],
        channels=[],
        defaults=DefaultModels(image_model="seedream-5-0-pro", video_model="MiniMax-H3"),
    )
    img = {row["id"]: row for row in payload["image_models"]}["seedream-5-0-pro"]
    assert img["allowed_resolutions"] == ["1K", "2K"]
    assert "3:4" in img["allowed_aspect_ratios"]
    assert img["description"]
    assert img["pricing_hint"]
    vid = {row["id"]: row for row in payload["video_models"]}["MiniMax-H3"]
    assert vid["duration_max"] == 15
    assert vid["allowed_resolutions"] == ["720p"]
    assert "MiniMax" in vid["description"] or vid["description"]
    assert vid["pricing_hint"]
    assert vid["eta_hint"]
    assert "分钟" in vid["eta_hint"]
