"""TokenFree 无语音渠道时，TTS 必须回退 edge-tts，禁止写静音成片。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.config import Settings
from app.services.ark import ArkGateway


def _tts_settings() -> Settings:
    return Settings(
        ark_mock=False,
        ark_api_key="sk-test",
        ark_base_url="https://www.tokenfree.com/v1",
        volc_tts_app_id="app",
        volc_tts_access_key="key",
    )


async def test_tts_tokenfree_falls_back_to_edge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """豆包 403、TokenFree seed-tts 无渠道时，用 edge-tts 产出可听文件。"""
    gw = ArkGateway(settings=_tts_settings())
    monkeypatch.setattr("app.services.storage.project_dir", lambda _pid: tmp_path)
    monkeypatch.setattr("app.services.storage.publish_local", lambda p: f"/static/{Path(p).name}")
    monkeypatch.setattr(gw, "_ark_api_key", lambda: "sk-test")
    monkeypatch.setattr(gw, "_tts_openspeech", AsyncMock(return_value=False))
    monkeypatch.setattr(gw, "_tts_openai_speech", AsyncMock(return_value=False))
    monkeypatch.setattr("app.services.ark.is_near_silent_audio", lambda _p: False)

    async def fake_edge(text: str, dest: Path, voice_hint: str = "") -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"a" * 4000)

    monkeypatch.setattr(gw, "_tts_edge", fake_edge)
    silence = AsyncMock()
    monkeypatch.setattr(gw, "_write_silence_mp3", silence)

    url = await gw.tts("你好。", "narrator_calm", project_id=1, shot_no=0)
    assert url.endswith("shot_000_tts.mp3")
    assert (tmp_path / "shot_000_tts.mp3").stat().st_size == 4000
    silence.assert_not_called()


async def test_tts_tokenfree_qwen_skips_speech_endpoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """qwen-tts 不得再打 /audio/speech，应直接走 Omni chat。"""
    gw = ArkGateway(settings=_tts_settings())
    monkeypatch.setattr("app.services.storage.project_dir", lambda _pid: tmp_path)
    monkeypatch.setattr("app.services.storage.publish_local", lambda p: f"/static/{Path(p).name}")
    monkeypatch.setattr(gw, "_ark_api_key", lambda: "sk-test")
    monkeypatch.setattr(gw, "_tts_openspeech", AsyncMock(return_value=False))
    monkeypatch.setattr("app.services.ark.is_near_silent_audio", lambda _p: False)
    captured: dict = {}

    async def fake_chat(text: str, voice: str, dest_path, *, model=None):
        dest_path.write_bytes(b"a" * 4000)
        captured["model"] = model
        captured["voice"] = voice
        return True

    chat = AsyncMock(side_effect=fake_chat)
    monkeypatch.setattr(gw, "_tts_openai_chat_audio", chat)

    class BoomClient:
        def __init__(self, *args, **kwargs):
            raise AssertionError("qwen-tts must not open HTTP for /audio/speech")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr("app.services.ark.httpx.AsyncClient", BoomClient)

    url = await gw.tts("你好。", "narrator_calm", project_id=1, shot_no=2)
    assert url.endswith("shot_002_tts.mp3")
    chat.assert_called()
    assert captured.get("model") == "qwen3-omni-flash"


async def test_tts_tokenfree_tried_before_edge_for_doubao_speaker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """豆包 speaker 也会走 TokenFree 多模型；成功则不再落到 edge-tts。"""
    gw = ArkGateway(settings=_tts_settings())
    monkeypatch.setattr("app.services.storage.project_dir", lambda _pid: tmp_path)
    monkeypatch.setattr("app.services.storage.publish_local", lambda p: f"/static/{Path(p).name}")
    monkeypatch.setattr(gw, "_ark_api_key", lambda: "sk-test")
    monkeypatch.setattr(gw, "_tts_openspeech", AsyncMock(return_value=False))
    speech = AsyncMock(return_value=True)
    monkeypatch.setattr(gw, "_tts_openai_speech", speech)
    monkeypatch.setattr("app.services.ark.is_near_silent_audio", lambda _p: False)

    async def fake_speech(text: str, voice: str, dest_path, *, model=None):
        dest_path.write_bytes(b"a" * 4000)
        return True

    speech.side_effect = fake_speech
    edge = AsyncMock()
    monkeypatch.setattr(gw, "_tts_edge", edge)

    url = await gw.tts(
        "你好。",
        "zh_male_shaonianzixin_uranus_bigtts",
        project_id=1,
        shot_no=3,
    )
    assert url.endswith("shot_003_tts.mp3")
    speech.assert_called()
    edge.assert_not_called()


async def test_tts_raises_when_all_providers_fail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """全部语音上游失败时直接报错，不再写静音文件冒充成功。"""
    gw = ArkGateway(settings=_tts_settings())
    monkeypatch.setattr("app.services.storage.project_dir", lambda _pid: tmp_path)
    monkeypatch.setattr(gw, "_ark_api_key", lambda: "sk-test")
    monkeypatch.setattr(gw, "_tts_openspeech", AsyncMock(return_value=False))
    monkeypatch.setattr(gw, "_tts_openai_speech", AsyncMock(return_value=False))

    async def fake_edge(text: str, dest: Path, voice_hint: str = "") -> None:
        raise RuntimeError("edge down")

    monkeypatch.setattr(gw, "_tts_edge", fake_edge)
    silence = AsyncMock()
    monkeypatch.setattr(gw, "_write_silence_mp3", silence)

    with pytest.raises(RuntimeError, match="配音失败"):
        await gw.tts("你好。", "narrator_calm", project_id=1, shot_no=0)
    silence.assert_not_called()


async def test_tts_edge_lengthens_connect_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """国内握手慢，edge-tts 必须把 connect_timeout 拉到 30 秒。"""
    import edge_tts

    captured: dict = {}

    class FakeCommunicate:
        def __init__(self, text: str, voice: str, **kwargs):
            captured.update(kwargs)
            captured["text"] = text
            captured["voice"] = voice

        async def save(self, path: str) -> None:
            Path(path).write_bytes(b"x" * 3000)

    monkeypatch.setattr(edge_tts, "Communicate", FakeCommunicate)
    gw = ArkGateway(settings=_tts_settings())
    dest = tmp_path / "shot.mp3"
    await gw._tts_edge("你好。", dest, voice_hint="narrator_calm")
    assert captured.get("connect_timeout") == 30
    assert dest.stat().st_size == 3000
