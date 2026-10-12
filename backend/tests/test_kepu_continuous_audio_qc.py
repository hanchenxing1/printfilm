# -*- coding: utf-8 -*-
"""整片连贯配音新合成后必须复查近静音，拒绝产出无声成片。"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services import pipeline


async def test_synthesize_rejects_near_silent_tts(tmp_path, monkeypatch) -> None:
    """TTS 返回近静音音频时抛错收敛，不继续按时长分配与合成。"""
    src = tmp_path / "tts_raw.mp3"
    src.write_bytes(b"x" * 4000)
    monkeypatch.setattr(
        "app.services.storage.local_path_from_url", lambda url: src
    )
    monkeypatch.setattr("app.services.storage.project_dir", lambda _pid: tmp_path)
    ark = SimpleNamespace(tts=AsyncMock(return_value="/static/p1/tts_raw.mp3"))
    with (
        patch.object(pipeline, "get_ark", return_value=ark),
        patch.object(pipeline, "_record_usage_est", AsyncMock()),
        patch.object(pipeline, "is_near_silent_audio", return_value=True),
        patch.object(pipeline, "probe_duration", AsyncMock(side_effect=AssertionError("不应继续探测时长"))),
    ):
        with pytest.raises(RuntimeError, match="近静音"):
            await pipeline._synthesize_continuous_audio(
                1,
                voice="zh-F1",
                shot_rows=[SimpleNamespace(id=1, duration=4.0, narration="你好")],
                force=True,
            )
    ark.tts.assert_awaited_once()
