"""TokenFree / New API 视频任务：路径映射与 Seedance 请求体包装。

方舟原生是 POST /contents/generations/tasks。TokenFree 走 OpenAI Videos 兼容接口：
POST /v1/videos、GET /v1/videos/:id、GET /v1/videos/:id/content。
"""

from __future__ import annotations

from typing import Any

from app.services.media_ref_limits import MAX_REFERENCE_IMAGES
from app.services.tokenfree_gateway import TOKENFREE_CHANNEL_ID

# 方舟原生异步视频任务前缀
ARK_VIDEO_TASK_PREFIX = "/contents/generations/tasks"
# TokenFree OpenAI Videos 兼容前缀（相对 /v1）
NEWAPI_VIDEO_TASK_PREFIX = "/videos"
# 任务成功态（方舟 + New API / OpenAI Videos）
VIDEO_SUCCESS_STATUSES = {"succeeded", "success", "completed", "complete"}
# 任务失败态
VIDEO_FAILED_STATUSES = {"failed", "cancelled", "canceled", "expired", "failure"}


def uses_tokenfree_video(*, base_url: str = "", channel_id: str = "") -> bool:
    """判断该基址/渠道是否走 New API 视频路径（而非方舟原生）。"""
    if (channel_id or "").strip().lower() == TOKENFREE_CHANNEL_ID:
        return True
    raw = (base_url or "").strip().lower()
    if "tokenfree.com" in raw:
        return True
    if "volces.com" in raw or "volcengineapi.com" in raw:
        return False
    return False


def remap_video_path(path: str, *, base_url: str = "", channel_id: str = "") -> str:
    """TokenFree 上将方舟任务路径改写成 /videos 与 /videos/{id}。"""
    normalized = path if str(path).startswith("/") else f"/{path}"
    if not uses_tokenfree_video(base_url=base_url, channel_id=channel_id):
        return normalized
    if normalized == ARK_VIDEO_TASK_PREFIX or normalized.startswith(ARK_VIDEO_TASK_PREFIX + "/"):
        return NEWAPI_VIDEO_TASK_PREFIX + normalized[len(ARK_VIDEO_TASK_PREFIX) :]
    return normalized


def tokenfree_video_content_url(base_url: str, task_id: str) -> str:
    """拼接 GET /v1/videos/{task_id}/content 下载地址。"""
    base = (base_url or "").rstrip("/")
    tid = (task_id or "").strip().lstrip("/")
    return f"{base}/videos/{tid}/content"


def is_tokenfree_content_url(url: str) -> bool:
    """是否为 TokenFree /videos/:id/content 拉取地址（下载需带 Bearer）。"""
    raw = (url or "").strip().lower()
    if "/videos/" not in raw:
        return False
    return raw.rstrip("/").endswith("/content")


def _media_url_from_item(item: dict[str, Any], key: str) -> str | None:
    """从 content 项取出 image_url / audio_url 的公网地址。"""
    raw = item.get(key)
    url = raw.get("url") if isinstance(raw, dict) else None
    if isinstance(url, str) and url.strip():
        return url.strip()
    return None


def wrap_seedance_payload_for_newapi(payload: dict[str, Any]) -> dict[str, Any]:
    """把方舟 Seedance body 转成 TokenFree POST /v1/videos 请求体。

    TokenFree 会把 metadata.input 转成下游插件 `{model, input}`。
    下游 Seedance 只认 reference_image_urls / first_frame_url，不认 content/images。
    多参考时禁止再写顶层 image / images，也不要把同一批图塞进 content，否则会按张数重复计数并触发参考图上限。
    """
    src = dict(payload)
    content = src.get("content")
    # texts 全部文案；images/audios 按 content 顺序；roles 用来区分首帧 vs 多参考
    texts: list[str] = []
    images: list[str] = []
    image_roles: list[str] = []
    audios: list[str] = []
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text":
                piece = str(item.get("text") or "").strip()
                if piece:
                    texts.append(piece)
            if item.get("type") == "image_url":
                url = _media_url_from_item(item, "image_url")
                if url:
                    images.append(url)
                    image_roles.append(str(item.get("role") or "").strip())
            if item.get("type") == "audio_url":
                url = _media_url_from_item(item, "audio_url")
                if url:
                    audios.append(url)
    prompt = "\n".join(texts) or str(src.get("prompt") or "").strip() or "."
    duration = src.get("duration")
    duration_text = ""
    if duration is not None:
        try:
            duration_text = str(int(duration))
        except (TypeError, ValueError):
            duration_text = str(duration).strip()
    ratio = str(src.get("ratio") or "").strip()
    uses_reference_images = any(role == "reference_image" for role in image_roles)
    capped_images: list[str] = []
    capped_roles: list[str] = []
    seen_urls: set[str] = set()
    for url, role in zip(images, image_roles):
        if url in seen_urls:
            continue
        seen_urls.add(url)
        capped_images.append(url)
        capped_roles.append(role)
        if len(capped_images) >= MAX_REFERENCE_IMAGES:
            break
    images = capped_images
    image_roles = capped_roles
    meta_input: dict[str, Any] = {}
    if duration_text:
        meta_input["duration"] = duration_text
    if ratio and ratio.lower() != "adaptive":
        meta_input["aspect_ratio"] = ratio
    resolution = str(src.get("resolution") or "").strip()
    if resolution:
        meta_input["resolution"] = resolution
    if "generate_audio" in src:
        meta_input["generate_audio"] = bool(src.get("generate_audio"))
    if "watermark" in src:
        meta_input["watermark"] = bool(src.get("watermark"))
    if "return_last_frame" in src:
        meta_input["return_last_frame"] = bool(src.get("return_last_frame"))
    if isinstance(content, list) and content:
        if uses_reference_images:
            # 下游会把 content 里的图也算进参考图上限，多参考只留文案/音频
            text_audio = [
                item
                for item in content
                if not (isinstance(item, dict) and item.get("type") == "image_url")
            ]
            if text_audio:
                meta_input["content"] = text_audio
        else:
            meta_input["content"] = content
    first_frame_url: str | None = None
    last_frame_url: str | None = None
    if images:
        if uses_reference_images:
            # 多参考：全部图只走 reference_image_urls（含衔接尾帧）
            meta_input["reference_image_urls"] = images
        else:
            # 纯首/尾帧：与 reference_* 互斥，按 role 填
            meta_input["images"] = images
            for url, role in zip(images, image_roles):
                if role == "first_frame" and not first_frame_url:
                    first_frame_url = url
                elif role == "last_frame":
                    last_frame_url = url
            first_frame_url = first_frame_url or images[0]
            meta_input["first_frame_url"] = first_frame_url
            if last_frame_url:
                meta_input["last_frame_url"] = last_frame_url
    if audios:
        meta_input["reference_audio_urls"] = audios[:10]
    out: dict[str, Any] = {
        "model": src.get("model"),
        "prompt": prompt,
        "metadata": {"input": meta_input},
    }
    if duration_text:
        out["seconds"] = duration_text
    if first_frame_url:
        out["image"] = first_frame_url
    elif images and not uses_reference_images:
        out["image"] = images[0]
    return out


def prepare_video_create_body(
    body: dict[str, Any],
    *,
    base_url: str = "",
    channel_id: str = "",
) -> dict[str, Any]:
    """按渠道决定是否包装 Seedance 请求体。"""
    if uses_tokenfree_video(base_url=base_url, channel_id=channel_id):
        return wrap_seedance_payload_for_newapi(body)
    return body


def unwrap_video_task_payload(data: dict[str, Any] | None) -> dict[str, Any]:
    """摊平 New API `{data: {...}}` 包装，便于取 status / url / task_id。"""
    if not isinstance(data, dict):
        return {}
    inner = data.get("data")
    if isinstance(inner, dict) and any(
        key in inner for key in ("status", "url", "content", "task_id", "id", "video_url")
    ):
        merged = dict(data)
        merged.update(inner)
        return merged
    return data


def _scalar_task_id(value: Any) -> str | None:
    """把标量任务 ID 收成非空字符串；忽略明显不是 ID 的状态词。"""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (str, int)) and str(value).strip():
        text = str(value).strip()
        if text.lower() in {"success", "ok", "true", "none", "null", "0"}:
            return None
        return text
    return None


def extract_video_task_id(data: dict[str, Any] | None) -> str | None:
    """从创建/查询响应取出轮询用任务 ID。

    New API 可能同时给 `id`（视频对象）和 `task_id`（查询用）；优先 task_id。
    部分网关把 ID 放在字符串 `data` 里。
    """
    if not isinstance(data, dict):
        return None
    payload = unwrap_video_task_payload(data)
    for key in ("task_id", "taskId"):
        found = _scalar_task_id(payload.get(key))
        if found:
            return found
    found = _scalar_task_id(data.get("data"))
    if found:
        return found
    return _scalar_task_id(payload.get("id"))


def format_video_task_error(err: Any) -> str:
    """把上游 error 对象收成可读短句。"""
    if isinstance(err, dict):
        for key in ("message", "msg", "error"):
            value = err.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, dict):
                nested = format_video_task_error(value)
                if nested:
                    return nested
        return "视频生成失败"
    text = str(err or "").strip()
    return text or "视频生成失败"


def extract_video_result_url(data: dict[str, Any]) -> str | None:
    """从任务成功响应中取视频 URL（New API `url` 或方舟 `content.video_url`）。"""
    for key in ("url", "video_url"):
        value = data.get(key)
        if isinstance(value, str) and value.strip().startswith(("http://", "https://", "/")):
            return value.strip()
    content = data.get("content")
    if isinstance(content, dict):
        for key in ("video_url", "url"):
            value = content.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def normalize_video_task_status(status: str) -> str:
    """把上游状态归一成 running/succeeded/failed。"""
    raw = (status or "").strip().lower()
    if raw in VIDEO_SUCCESS_STATUSES:
        return "succeeded"
    if raw in VIDEO_FAILED_STATUSES:
        return "failed"
    return "running"
