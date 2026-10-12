# -*- coding: utf-8 -*-
"""Seedance 清晰度能力推断与钳制。"""
from __future__ import annotations

from app.services.seedance_resolutions import (
    allowed_video_resolutions,
    clamp_video_resolution,
)


def test_mini_excludes_1080p() -> None:
    assert allowed_video_resolutions("seedance-2-0-mini") == ["480p", "720p"]
    assert allowed_video_resolutions("bytedance/seedance-2-fast") == ["480p", "720p"]


def test_seedance_25_allows_1080p() -> None:
    assert allowed_video_resolutions("seedance-2.5") == ["480p", "720p", "1080p"]
    assert allowed_video_resolutions("doubao-seedance-2-5-xxx") == [
        "480p",
        "720p",
        "1080p",
    ]


def test_seedance_20_excludes_1080p() -> None:
    assert allowed_video_resolutions("doubao-seedance-2-0-260128") == ["480p", "720p"]
    assert allowed_video_resolutions("seedance-2.0") == ["480p", "720p"]
    assert allowed_video_resolutions("seedance-2-0") == ["480p", "720p"]
    assert allowed_video_resolutions("seedance-2") == ["480p", "720p"]


def test_unknown_defaults_safe() -> None:
    assert allowed_video_resolutions("") == ["480p", "720p"]
    assert allowed_video_resolutions("some-other-video") == ["480p", "720p"]


def test_minimax_h3_only_720p() -> None:
    assert allowed_video_resolutions("MiniMax-H3") == ["720p"]
    assert allowed_video_resolutions("minimax-h3") == ["720p"]
    assert clamp_video_resolution("MiniMax-H3", "1080p") == "720p"
    assert clamp_video_resolution("MiniMax-H3", "480p") == "720p"


def test_clamp_1080p_on_mini_to_720p() -> None:
    assert clamp_video_resolution("seedance-2-0-mini", "1080p") == "720p"
    assert clamp_video_resolution("seedance-2-0-mini", "720p") == "720p"
    assert clamp_video_resolution("seedance-2-0-mini", None) == "720p"


def test_clamp_keeps_1080p_on_25() -> None:
    assert clamp_video_resolution("seedance-2.5", "1080p") == "1080p"


def test_clamp_1080p_on_seedance_20_to_720p() -> None:
    assert clamp_video_resolution("doubao-seedance-2-0-260128", "1080p") == "720p"
    assert clamp_video_resolution("seedance-2-0", "1080p") == "720p"


def test_build_body_clamps_resolution_by_model() -> None:
    from app.services.drama.build_seedance_generate_body import build_seedance_generate_body

    body = build_seedance_generate_body(
        {
            "content": "测试旁白",
            "model_id": "seedance-2-0-mini",
            "resolution": "1080p",
            "aspect_ratio": "9:16",
            "duration_fallback": 5,
        }
    )
    assert body["resolution"] == "720p"


def test_catalog_video_row_has_allowed_resolutions() -> None:
    from app.schemas_routing import DefaultModels, LogicalModel
    from app.services.media_catalog import build_media_catalog

    payload = build_media_catalog(
        logical_models=[
            LogicalModel(
                id="seedance-2-0-mini",
                name="Seedance Mini",
                capability="video",
                enabled=True,
                bindings=[],
            ),
            LogicalModel(
                id="seedance-2.5",
                name="Seedance 2.5",
                capability="video",
                enabled=True,
                bindings=[],
            ),
            LogicalModel(
                id="doubao-seedance-2-0-260128",
                name="Seedance 2.0",
                capability="video",
                enabled=True,
                bindings=[],
            ),
        ],
        channels=[],
        defaults=DefaultModels(video_model="seedance-2-0-mini"),
    )
    by_id = {row["id"]: row for row in payload["video_models"]}
    assert by_id["seedance-2-0-mini"]["allowed_resolutions"] == ["480p", "720p"]
    assert by_id["seedance-2-5"]["allowed_resolutions"] == ["480p", "720p", "1080p"]
    assert by_id["seedance-2-5"]["label"] == "Seedance 2.5"
    # 别名 / 上游长 id 归一后不应再单独占一行 1080p 的 2.0
    assert "seedance-2.5" not in by_id
    assert by_id["seedance-2-0"]["allowed_resolutions"] == ["480p", "720p"]
    assert by_id["seedance-2-0"]["label"] == "Seedance 2.0"
