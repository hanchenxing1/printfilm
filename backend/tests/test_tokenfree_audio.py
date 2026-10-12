"""TokenFree 音频路由检测。"""

import base64

from app.services.tokenfree_audio import (
    extract_chat_audio_bytes,
    extract_sse_audio_bytes,
    iter_tokenfree_tts_models,
    resolve_tokenfree_tts_model,
    tokenfree_speech_honors_speaker,
    tokenfree_speech_voice,
    tokenfree_tts_chat_model,
    tokenfree_tts_uses_chat_audio,
    tokenfree_tts_uses_omni_stream,
    uses_tokenfree_audio,
    wrap_pcm_s16le_wav,
)
from app.services.tokenfree_gateway import TOKENFREE_BASE_URL, TOKENFREE_CHANNEL_ID


def test_uses_tokenfree_audio():
    assert uses_tokenfree_audio(base_url=TOKENFREE_BASE_URL, channel_id=TOKENFREE_CHANNEL_ID)
    assert uses_tokenfree_audio(base_url="https://www.tokenfree.com/v1") is True
    assert uses_tokenfree_audio(base_url="https://ark.cn-beijing.volces.com/api/v3") is False


def test_resolve_tokenfree_tts_model_replaces_seed_tts():
    assert resolve_tokenfree_tts_model("seed-tts-2.0") == "qwen-tts-2025-05-22"
    assert resolve_tokenfree_tts_model("") == "qwen-tts-2025-05-22"
    assert resolve_tokenfree_tts_model("qwen-tts-2025-05-22") == "qwen-tts-2025-05-22"


def test_tokenfree_speech_voice_gender():
    assert tokenfree_speech_voice("zh_female_cancan_uranus_bigtts") == "Cherry"
    assert tokenfree_speech_voice("zh_male_shaonianzixin_uranus_bigtts") == "Ethan"
    assert tokenfree_speech_voice("Cherry") == "Cherry"
    assert tokenfree_speech_voice("zh_female_cancan_uranus_bigtts", "gemini-3.1-flash-tts") == "Kore"
    assert tokenfree_speech_voice("zh_male_shaonianzixin_uranus_bigtts", "elevenlabs-tts") == "Adam"


def test_tokenfree_speech_does_not_honor_doubao_ids():
    assert tokenfree_speech_honors_speaker("Cherry") is True
    assert tokenfree_speech_honors_speaker("ethan") is True
    assert tokenfree_speech_honors_speaker("zh_male_shaonianzixin_uranus_bigtts") is False
    assert tokenfree_speech_honors_speaker("S_abc") is False


def test_iter_tokenfree_tts_models_puts_preferred_first():
    models = iter_tokenfree_tts_models("gemini-3.1-flash-tts")
    assert models[0] == "gemini-3.1-flash-tts"
    assert "qwen3-omni-flash" in models
    assert "qwen-tts-2025-05-22" not in models
    assert "elevenlabs-tts" in models
    assert models.count("gemini-3.1-flash-tts") == 1
    assert models.count("qwen3-omni-flash") == 1


def test_qwen_tts_is_remapped_to_omni_chat():
    assert tokenfree_tts_chat_model("qwen-tts-2025-05-22") == "qwen3-omni-flash"
    assert iter_tokenfree_tts_models("qwen-tts-2025-05-22")[0] == "qwen3-omni-flash"
    assert tokenfree_tts_uses_chat_audio("qwen-tts-2025-05-22") is True
    assert tokenfree_tts_uses_omni_stream("qwen3-omni-flash") is True


def test_tokenfree_tts_uses_chat_audio_for_gemini():
    assert tokenfree_tts_uses_chat_audio("gemini-3.1-flash-tts") is True
    assert tokenfree_tts_uses_chat_audio("qwen3-omni-flash") is True


def test_extract_chat_audio_bytes_from_message():
    blob = base64.b64encode(b"a" * 1200).decode("ascii")
    got = extract_chat_audio_bytes({"choices": [{"message": {"audio": {"data": blob}}}]})
    assert got == b"a" * 1200


def test_extract_sse_audio_bytes_concatenates_chunks():
    part = base64.b64encode(b"a" * 600).decode("ascii")
    raw = (
        'data: {"choices":[{"delta":{"audio":{"data":"%s"}}}]}\n\n'
        'data: {"choices":[{"delta":{"audio":{"data":"%s"}}}]}\n\n'
        "data: [DONE]\n"
    ) % (part, part)
    got = extract_sse_audio_bytes(raw)
    assert got == b"a" * 1200


def test_extract_sse_audio_bytes_drops_error_stream():
    raw = 'data: {"error":{"message":"Field required: input.text"}}\n\n'
    assert extract_sse_audio_bytes(raw) is None


def test_wrap_pcm_s16le_wav_adds_riff_header():
    pcm = b"\x00\x01" * 600
    wav = wrap_pcm_s16le_wav(pcm)
    assert wav.startswith(b"RIFF")
    assert wav[8:12] == b"WAVE"
    assert wav.endswith(pcm)

