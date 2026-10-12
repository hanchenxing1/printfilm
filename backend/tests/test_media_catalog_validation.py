"""项目 image_model / video_model 校验与前台目录一致。"""

from app.services.media_catalog import is_valid_project_media_model


def test_legacy_seedream_names_infer_image():
    """旧项目里的 kie-/ark- 名仍可按能力推断，避免打开项目直接校验失败。"""
    assert is_valid_project_media_model("kie-seedream-5", "image") is True
    assert is_valid_project_media_model("ark-seedream", "image") is True


def test_empty_model_allowed():
    assert is_valid_project_media_model("", "image") is True
    assert is_valid_project_media_model("  ", "video") is True


def test_garbage_model_rejected():
    assert is_valid_project_media_model("not-a-real-model-xyz", "image") is False


def test_tokenfree_style_ids_infer_capability():
    from app.services.model_routing_config import infer_model_capability

    assert infer_model_capability("gpt-image-2-5") == "image"
    assert infer_model_capability("seedance-2-0-mini") == "video"
    assert infer_model_capability("kie-veo3-fast") == "video"
    assert infer_model_capability("kie-seedream-5") == "image"
    assert infer_model_capability("nano-banana-2") == "image"
    assert infer_model_capability("qwen-tts-2025-05-22") == "audio"
    assert infer_model_capability("gemini-3.1-flash-tts") == "audio"
    assert infer_model_capability("elevenlabs/text-to-speech-multilingual-v2") == "audio"
    assert infer_model_capability("elevenlabs-tts") == "audio"


def test_minimax_h3_uses_tokenfree_pricing_tags_as_video():
    """价目 tags 优先：假模型名无 video 关键字时仍归视频。"""
    from app.services.model_routing_config import infer_model_capability
    from app.services.tokenfree_pricing import parse_pricing_payload, set_cached_rates

    set_cached_rates(
        parse_pricing_payload(
            {
                "data": [
                    {
                        "model_name": "tf-omni-gen-x",
                        "tags": "Hailuo,Video,Text to Video,Image to Video",
                        "supported_endpoint_types": ["openai", "openai-video", "openai-response"],
                        "quota_type": 0,
                        "model_ratio": 37.5,
                        "completion_ratio": 1,
                        "model_price": 0,
                    }
                ]
            }
        )
    )
    try:
        assert infer_model_capability("tf-omni-gen-x") == "video"
        assert infer_model_capability("MiniMax-H3") == "video"  # 名字兜底
    finally:
        set_cached_rates(None)


def test_catalog_payload_uses_tokenfree_routing() -> None:
    from app.schemas_routing import DefaultModels, LogicalModel, SystemModelChannel
    from app.services.media_catalog import build_media_catalog

    payload = build_media_catalog(
        logical_models=[
            LogicalModel(id="seedream-5.0", name="Seedream 5.0", capability="image", enabled=True),
            LogicalModel(id="seedance-2.5", name="Seedance 2.5", capability="video", enabled=True),
        ],
        channels=[
            SystemModelChannel(
                id="tokenfree",
                name="TokenFree",
                base_url="https://www.tokenfree.com/v1",
                models=["doubao-seedance-2-5-260628"],
                enabled=True,
            )
        ],
        defaults=DefaultModels(image_model="seedream-5.0", video_model="seedance-2.5"),
    )
    assert payload["defaults"]["video_model"] == "seedance-2-5"
    assert payload["defaults"]["image_model"] == "seedream-5-0-pro"
    assert any(m["id"] == "seedance-2-5" for m in payload["video_models"])
    assert any(m["id"] == "seedream-5-0-pro" for m in payload["image_models"])
    # 点分旧 id 不得残留为独立目录行
    assert not any(m["id"] == "seedream-5.0" for m in payload["image_models"])
    assert not any(m["id"] in {"seedance-2", "seedance-2.5"} for m in payload["video_models"])
    # recommended 落在规范 id 上
    img_by_id = {m["id"]: m for m in payload["image_models"]}
    assert img_by_id["seedream-5-0-pro"]["recommended"] is True
    assert all(m["provider"] == "tokenfree" for m in payload["video_models"])
    assert not any("kie" in m["id"] for m in payload["video_models"])
    assert not any("方舟" in m["label"] for m in payload["video_models"])
    labels = [m["label"] for m in payload["video_models"]]
    assert "Seedance 2.0" in labels
    assert "Seedance 2.0 Mini" in labels
    assert "Seedance 2.5" in labels
