"""TokenFree / New API 语音：Qwen-TTS 的 /audio/speech 未实现，改走 Omni 流式 chat。"""

from __future__ import annotations

import base64
import json
import struct
from typing import Any

from app.services.tokenfree_gateway import TOKENFREE_CHANNEL_ID

# 管理端逻辑名仍是 qwen-tts；真正发请求时改打 Omni（Ali ConvertAudioRequest 未实现）
TOKENFREE_DEFAULT_TTS_MODEL = "qwen-tts-2025-05-22"
TOKENFREE_OMNI_TTS_MODEL = "qwen3-omni-flash"

# 配音时按顺序试：管理端默认模型优先，其余作同渠道兜底
TOKENFREE_TTS_FALLBACKS: tuple[str, ...] = (
    "qwen-tts-2025-05-22",
    "qwen3-omni-flash",
    "qwen3-tts-flash",
    "gemini-3.1-flash-tts",
    "gemini-2.5-pro-preview-tts",
    "elevenlabs-tts",
    "elevenlabs/text-to-speech-multilingual-v2",
)

# Omni 流式口播：禁止改写原文
TOKENFREE_OMNI_TTS_SYSTEM = "你是语音合成器。只朗读用户给出的原文，禁止改写、解释或添加任何额外句子。"
# Omni 流式 PCM 实测为 24 kHz / 16-bit / mono
TOKENFREE_OMNI_PCM_RATE = 24000

_SEED_TTS_MARKERS = ("seed-tts",)


def uses_tokenfree_audio(*, base_url: str = "", channel_id: str = "") -> bool:
    """判断 TTS 是否应走 TokenFree（与视频、LLM 同一 Base URL / Key）。"""
    if (channel_id or "").strip().lower() == TOKENFREE_CHANNEL_ID:
        return True
    raw = (base_url or "").strip().lower()
    if "tokenfree.com" in raw:
        return True
    if "volces.com" in raw or "volcengineapi.com" in raw:
        return False
    return False


def resolve_tokenfree_tts_model(model: str | None) -> str:
    """把已下线的 seed-tts 换成目录内默认 Qwen TTS。"""
    mid = (model or "").strip()
    low = mid.lower()
    if not mid or any(mark in low for mark in _SEED_TTS_MARKERS):
        return TOKENFREE_DEFAULT_TTS_MODEL
    return mid


def tokenfree_tts_chat_model(model: str) -> str:
    """qwen-tts 在 TokenFree 阿里渠道上 /audio/speech 未实现，改打 Omni 流式 chat。"""
    low = (model or "").casefold()
    if "qwen-tts" in low:
        return TOKENFREE_OMNI_TTS_MODEL
    return model


def iter_tokenfree_tts_models(preferred: str | None) -> list[str]:
    """默认语音模型 + TokenFree 目录里其它 TTS，去重保序；qwen-tts 折叠成 Omni。"""
    seen: set[str] = set()
    out: list[str] = []
    for raw in (preferred, *TOKENFREE_TTS_FALLBACKS):
        mid = tokenfree_tts_chat_model(resolve_tokenfree_tts_model(raw))
        key = mid.casefold()
        if not mid or key in seen:
            continue
        seen.add(key)
        out.append(mid)
    return out


def tokenfree_tts_uses_chat_audio(model: str) -> bool:
    """Gemini TTS / Qwen-TTS / Qwen-Omni 都走 chat 出音频，不要打 /audio/speech。"""
    low = (model or "").casefold()
    if "gemini" in low and "tts" in low:
        return True
    if "qwen-tts" in low:
        return True
    return "omni" in low


def tokenfree_tts_uses_omni_stream(model: str) -> bool:
    """Qwen-Omni 必须 stream + modalities audio，非流式会缺 input.text 或不出声。"""
    low = (model or "").casefold()
    return "omni" in low or "qwen-tts" in low


# qwen-tts 实际认的音色名；豆包 zh_* / S_ 不在此列
_TOKENFREE_NATIVE_VOICES = frozenset({"Cherry", "Serena", "Ethan", "Chelsie", "alloy"})
_TOKENFREE_NATIVE_VOICES_FOLD = {v.casefold(): v for v in _TOKENFREE_NATIVE_VOICES}


def tokenfree_speech_honors_speaker(speaker: str) -> bool:
    """qwen-tts 只接受少数英文音色；豆包 id 会被压成 Ethan/Cherry。"""
    return (speaker or "").strip().casefold() in _TOKENFREE_NATIVE_VOICES_FOLD


def _speaker_is_male(speaker: str) -> bool:
    """豆包 speaker id / 英文音色名是否按男声映射。"""
    low = (speaker or "").strip().lower()
    return low.startswith("zh_male") or "_male_" in low


def tokenfree_speech_voice(speaker: str, model: str = "") -> str:
    """豆包 speaker id → 当前 TTS 模型能认的音色。"""
    raw = (speaker or "").strip()
    native = _TOKENFREE_NATIVE_VOICES_FOLD.get(raw.casefold())
    mid = (model or "").casefold()
    if native and "gemini" not in mid and "eleven" not in mid:
        return native
    male = _speaker_is_male(raw)
    if "gemini" in mid:
        return "Puck" if male else "Kore"
    if "eleven" in mid:
        return "Adam" if male else "Rachel"
    if native:
        return native
    return "Ethan" if male else "Cherry"


def extract_chat_audio_bytes(payload: dict[str, Any]) -> bytes | None:
    """从 chat/completions 或 DashScope 包里取出音频字节。"""
    if not isinstance(payload, dict):
        return None
    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        msg = choices[0].get("message") if isinstance(choices[0], dict) else None
        if isinstance(msg, dict):
            got = _audio_bytes_from_obj(msg.get("audio"))
            if got:
                return got
            got = _audio_bytes_from_obj(msg.get("content"))
            if got:
                return got
    output = payload.get("output")
    if isinstance(output, dict):
        got = _audio_bytes_from_obj(output.get("audio"))
        if got:
            return got
    return _audio_bytes_from_obj(payload.get("audio") or payload.get("data"))


def _audio_bytes_from_obj(raw: Any) -> bytes | None:
    """解析 base64 / data URL / 嵌套 data 字段。"""
    if isinstance(raw, str) and raw.strip():
        text = raw.strip()
        if text.startswith("data:") and "," in text:
            text = text.split(",", 1)[1]
        try:
            data = base64.b64decode(text, validate=False)
        except Exception:  # noqa: BLE001
            return None
        return data if len(data) >= 1000 else None
    if isinstance(raw, dict):
        for key in ("data", "b64_json", "audio"):
            got = _audio_bytes_from_obj(raw.get(key))
            if got:
                return got
    return None


def _decode_audio_chunk(raw: Any) -> bytes:
    """SSE 分片可能远小于 1KB，这里不按整段音频门槛丢弃。"""
    if isinstance(raw, str) and raw.strip():
        text = raw.strip()
        if text.startswith("data:") and "," in text:
            text = text.split(",", 1)[1]
        try:
            return base64.b64decode(text, validate=False)
        except Exception:  # noqa: BLE001
            return b""
    if isinstance(raw, dict):
        for key in ("data", "b64_json", "audio"):
            got = _decode_audio_chunk(raw.get(key))
            if got:
                return got
    return b""


def extract_sse_audio_bytes(raw: str) -> bytes | None:
    """从 Omni / chat SSE 里拼接 delta.audio.data。"""
    chunks: list[bytes] = []
    for line in (raw or "").splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            obj = json.loads(payload)
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(obj, dict):
            continue
        if isinstance(obj.get("error"), dict) and not chunks:
            return None
        for choice in obj.get("choices") or []:
            if not isinstance(choice, dict):
                continue
            delta = choice.get("delta") if isinstance(choice.get("delta"), dict) else {}
            message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
            blob = _decode_audio_chunk((delta or {}).get("audio") or (message or {}).get("audio"))
            if blob:
                chunks.append(blob)
    joined = b"".join(chunks)
    return joined if len(joined) >= 1000 else None


def _looks_like_mpeg(raw: bytes) -> bool:
    """识别无 ID3 的 MP3 帧头（含 \\xff\\xfa 等）。"""
    return len(raw) >= 2 and raw[0] == 0xFF and (raw[1] & 0xE0) == 0xE0


def wrap_pcm_s16le_wav(pcm: bytes, *, sample_rate: int = TOKENFREE_OMNI_PCM_RATE, channels: int = 1) -> bytes:
    """把 Omni 流式 PCM 包成 WAV；已是 RIFF/MP3 则原样返回。"""
    if len(pcm) < 1000:
        return b""
    if pcm[:4] == b"RIFF" or pcm[:3] == b"ID3" or _looks_like_mpeg(pcm):
        return pcm
    byte_rate = sample_rate * channels * 2
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + len(pcm),
        b"WAVE",
        b"fmt ",
        16,
        1,
        channels,
        sample_rate,
        byte_rate,
        channels * 2,
        16,
        b"data",
        len(pcm),
    )
    return header + pcm


def build_omni_tts_chat_body(text: str, voice: str, model: str) -> dict[str, Any]:
    """构造 Qwen-Omni 流式配音请求体。"""
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": TOKENFREE_OMNI_TTS_SYSTEM},
            {"role": "user", "content": text},
        ],
        "modalities": ["text", "audio"],
        "audio": {"voice": voice, "format": "wav"},
        "stream": True,
        "stream_options": {"include_usage": True},
    }
