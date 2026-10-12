"""TokenFree / New API 视频路径与 Seedance 请求体包装。"""

from __future__ import annotations

from app.services.ark import ArkGateway, _build_task_result_from_payload
from app.services.media_ref_limits import MAX_REFERENCE_IMAGES
from app.services.tokenfree_gateway import TOKENFREE_BASE_URL, TOKENFREE_CHANNEL_ID
from app.services.tokenfree_video import (
    extract_video_task_id,
    prepare_video_create_body,
    remap_video_path,
    uses_tokenfree_video,
    wrap_seedance_payload_for_newapi,
)


def test_remap_video_path_on_tokenfree():
    create = remap_video_path(
        "/contents/generations/tasks",
        base_url=TOKENFREE_BASE_URL,
        channel_id=TOKENFREE_CHANNEL_ID,
    )
    poll = remap_video_path(
        "/contents/generations/tasks/task-1",
        base_url=TOKENFREE_BASE_URL,
    )
    assert create == "/videos"
    assert poll == "/videos/task-1"


def test_remap_video_path_keeps_ark_volces():
    path = remap_video_path(
        "/contents/generations/tasks",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
    )
    assert path == "/contents/generations/tasks"
    assert uses_tokenfree_video(base_url="https://ark.cn-beijing.volces.com/api/v3") is False


def test_wrap_seedance_payload_uses_videos_metadata_input():
    payload = {
        "model": "seedance-2-5",
        "content": [
            {"type": "text", "text": "镜头推进"},
            {
                "type": "image_url",
                "image_url": {"url": "https://cdn.example.com/a.jpg"},
                "role": "first_frame",
            },
        ],
        "duration": 5,
        "resolution": "720p",
        "ratio": "16:9",
        "watermark": False,
        "generate_audio": True,
        "return_last_frame": True,
    }
    wrapped = wrap_seedance_payload_for_newapi(payload)
    assert wrapped["model"] == "seedance-2-5"
    assert wrapped["prompt"] == "镜头推进"
    assert wrapped["image"] == "https://cdn.example.com/a.jpg"
    assert wrapped["seconds"] == "5"
    meta_input = wrapped["metadata"]["input"]
    assert meta_input["duration"] == "5"
    assert meta_input["aspect_ratio"] == "16:9"
    assert meta_input["content"] == payload["content"]
    assert meta_input["generate_audio"] is True
    assert meta_input["first_frame_url"] == "https://cdn.example.com/a.jpg"
    assert "reference_image_urls" not in meta_input
    assert "content" not in wrapped


def test_wrap_seedance_payload_keeps_all_reference_images():
    """多参考必须写成 reference_image_urls，不能只留顶层第一张图。"""
    payload = {
        "model": "seedance-2-5",
        "content": [
            {"type": "text", "text": "光光飞过"},
            {
                "type": "image_url",
                "image_url": {"url": "https://cdn.example.com/guang.png"},
                "role": "reference_image",
            },
            {
                "type": "image_url",
                "image_url": {"url": "https://cdn.example.com/mimi.png"},
                "role": "reference_image",
            },
            {
                "type": "image_url",
                "image_url": {"url": "https://cdn.example.com/last.jpg"},
                "role": "reference_image",
            },
            {
                "type": "audio_url",
                "audio_url": {"url": "https://cdn.example.com/voice.mp3"},
                "role": "reference_audio",
            },
        ],
        "duration": 22,
        "resolution": "480p",
        "ratio": "16:9",
        "watermark": False,
        "generate_audio": True,
        "return_last_frame": True,
    }
    wrapped = wrap_seedance_payload_for_newapi(payload)
    meta_input = wrapped["metadata"]["input"]
    refs = [
        "https://cdn.example.com/guang.png",
        "https://cdn.example.com/mimi.png",
        "https://cdn.example.com/last.jpg",
    ]
    assert "image" not in wrapped
    assert "images" not in wrapped
    assert meta_input["reference_image_urls"] == refs
    assert "images" not in meta_input
    assert all(
        not (isinstance(item, dict) and item.get("type") == "image_url")
        for item in meta_input.get("content") or []
    )
    assert meta_input["reference_audio_urls"] == ["https://cdn.example.com/voice.mp3"]
    assert "first_frame_url" not in meta_input
    assert "image" not in meta_input


def test_wrap_seedance_payload_single_reference_image_keeps_ratio_mode():
    """有画幅的单张 i2v 也是 reference_image，不能退化成 first_frame。"""
    payload = {
        "model": "seedance-2-5",
        "content": [
            {"type": "text", "text": "镜头推进"},
            {
                "type": "image_url",
                "image_url": {"url": "https://cdn.example.com/a.jpg"},
                "role": "reference_image",
            },
        ],
        "duration": 5,
        "ratio": "9:16",
        "resolution": "480p",
    }
    wrapped = wrap_seedance_payload_for_newapi(payload)
    meta_input = wrapped["metadata"]["input"]
    assert "images" not in wrapped
    assert "image" not in wrapped
    assert meta_input["reference_image_urls"] == ["https://cdn.example.com/a.jpg"]
    assert "images" not in meta_input
    assert meta_input["aspect_ratio"] == "9:16"
    assert "first_frame_url" not in meta_input


def test_wrap_seedance_payload_from_generate_body_includes_continuity():
    """真实组装体：角色图 + 上一镜尾帧都要进 reference_image_urls。"""
    from app.services.drama.build_seedance_generate_body import build_seedance_generate_body

    body = build_seedance_generate_body(
        {
            "content": "@duration:6\n禹：水患未平。",
            "aspect_ratio": "16:9",
            "resolution": "480p",
            "duration_fallback": 8,
            "continuity_first_frame_url": "https://cdn.example.com/prev_last.jpg",
            "reference": [
                {
                    "id": 1,
                    "type": "character",
                    "name": "禹",
                    "cover": "https://cdn.example.com/yu.jpg",
                    "url": "https://cdn.example.com/yu.jpg",
                    "params": {},
                }
            ],
        }
    )
    wrapped = wrap_seedance_payload_for_newapi(body)
    refs = wrapped["metadata"]["input"]["reference_image_urls"]
    assert refs[0] == "https://cdn.example.com/yu.jpg"
    assert refs[-1] == "https://cdn.example.com/prev_last.jpg"
    assert "image" not in wrapped
    assert "images" not in wrapped
    assert "images" not in wrapped["metadata"]["input"]
    assert "first_frame_url" not in wrapped["metadata"]["input"]


def test_wrap_seedance_payload_caps_reference_images():
    """下游最多 9 张；同一批图不得在 content / images 里再写一份。"""
    content = [{"type": "text", "text": "群戏"}]
    for i in range(12):
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"https://cdn.example.com/{i}.png"},
                "role": "reference_image",
            }
        )
    wrapped = wrap_seedance_payload_for_newapi(
        {"model": "seedance-2-5", "content": content, "duration": 8}
    )
    refs = wrapped["metadata"]["input"]["reference_image_urls"]
    assert len(refs) == MAX_REFERENCE_IMAGES
    assert "images" not in wrapped
    assert "images" not in wrapped["metadata"]["input"]
    assert all(
        not (isinstance(item, dict) and item.get("type") == "image_url")
        for item in wrapped["metadata"]["input"].get("content") or []
    )


def test_prepare_video_create_body_only_wraps_tokenfree():
    body = {"model": "seedance-2-5", "content": [{"type": "text", "text": "hi"}], "duration": 5}
    ark = prepare_video_create_body(
        body,
        base_url="https://ark.cn-beijing.volces.com/api/v3",
    )
    tf = prepare_video_create_body(body, base_url=TOKENFREE_BASE_URL)
    assert ark["content"][0]["text"] == "hi"
    assert tf["prompt"] == "hi"
    assert tf["metadata"]["input"]["duration"] == "5"
    assert tf["metadata"]["input"]["content"] == body["content"]


def test_extract_video_task_id_from_newapi_and_wrapped_data():
    assert extract_video_task_id({"task_id": "abc"}) == "abc"
    assert extract_video_task_id({"id": "ark-1"}) == "ark-1"
    assert extract_video_task_id({"data": {"task_id": "nested"}}) == "nested"
    assert extract_video_task_id({"id": "video_123", "task_id": "abcd"}) == "abcd"
    assert extract_video_task_id({"id": "outer", "data": {"task_id": "nested", "status": "queued"}}) == "nested"
    assert extract_video_task_id({"code": "success", "data": "cgt-xxx"}) == "cgt-xxx"


def test_build_task_result_from_newapi_completed_url():
    result = _build_task_result_from_payload(
        {
            "task_id": "abcd",
            "status": "completed",
            "url": "https://example.com/video.mp4",
        }
    )
    assert result.status == "succeeded"
    assert result.url == "https://example.com/video.mp4"


def test_build_task_result_from_newapi_nested_data():
    result = _build_task_result_from_payload(
        {
            "data": {
                "status": "succeeded",
                "content": {"video_url": "https://example.com/ark.mp4"},
            }
        }
    )
    assert result.status == "succeeded"
    assert result.url == "https://example.com/ark.mp4"


def test_ark_client_tokenfree_video_url():
    from app.config import get_settings

    settings = get_settings().model_copy(update={"ark_base_url": TOKENFREE_BASE_URL})
    client = ArkGateway(settings=settings)
    assert client._url("/contents/generations/tasks") == f"{TOKENFREE_BASE_URL}/videos"
    assert client._url("/contents/generations/tasks/t1") == f"{TOKENFREE_BASE_URL}/videos/t1"
    wrapped = client._video_json(
        {
            "model": "seedance-2-5",
            "content": [{"type": "text", "text": "hi"}],
            "duration": 5,
            "ratio": "16:9",
        }
    )
    assert wrapped["prompt"] == "hi"
    assert wrapped["metadata"]["input"]["duration"] == "5"
    assert wrapped["metadata"]["input"]["aspect_ratio"] == "16:9"
    finalized = client._finalize_video_result(
        _build_task_result_from_payload({"status": "completed"}),
        "task-9",
    )
    assert finalized.status == "succeeded"
    assert finalized.url == f"{TOKENFREE_BASE_URL}/videos/task-9/content"
