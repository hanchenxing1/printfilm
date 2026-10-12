"""科普逐镜衔接：后镜出图参考上一镜静帧，出视频参考上一镜尾帧。"""

from types import SimpleNamespace

from app.services.kepu_continuity import (
    image_refs_for_shot,
    persist_last_frame_from_video,
    previous_shot,
    previous_usable_shot,
    shot_image_ref,
    shot_last_frame_ref,
    video_extra_refs_for_shot,
)


def _shot(**kwargs):
    """构造带默认镜号的分镜代理。"""
    data = {"shot_no": 1, "image_ark_url": None, "image_url": None, "last_frame_url": None}
    data.update(kwargs)
    return SimpleNamespace(**data)


def test_previous_shot_picks_immediate_predecessor():
    """乱序分镜列表仍取 shot_no 紧邻的上一镜。"""
    shots = [_shot(shot_no=1), _shot(shot_no=3), _shot(shot_no=2)]
    prev = previous_shot(shots, 3)
    assert prev is not None
    assert prev.shot_no == 2
    assert previous_shot(shots, 1) is None


def test_image_refs_for_shot_puts_prev_still_first():
    """后镜出图把上一镜 CDN 静帧放在参考列表最前。"""
    prev = _shot(image_ark_url="https://cdn.example.com/shot1.png")
    refs = image_refs_for_shot(prev, ["https://cdn.example.com/style.png"])
    assert refs[0] == "https://cdn.example.com/shot1.png"
    assert "https://cdn.example.com/style.png" in refs


def test_image_refs_skip_local_static_and_keep_template():
    """Seedream 丢弃本地 /static，仍保留模板公网底图。"""
    prev = _shot(image_url="/static/generated/p1/shot_001.png")
    refs = image_refs_for_shot(prev, ["https://cdn.example.com/style.png"])
    assert refs == ["https://cdn.example.com/style.png"]
    assert shot_image_ref(prev) is None


def test_video_extra_refs_prefer_last_frame_even_if_local():
    """出视频优先用上一镜尾帧，本地路径留给 Seedance resolve。"""
    prev = _shot(
        last_frame_url="/static/generated/p1/shot_001_last.jpg",
        image_ark_url="https://cdn.example.com/shot1.png",
    )
    assert video_extra_refs_for_shot(prev) == ["/static/generated/p1/shot_001_last.jpg"]
    assert shot_last_frame_ref(prev) == "/static/generated/p1/shot_001_last.jpg"


def test_video_extra_refs_fall_back_to_prev_still():
    """没有尾帧时退回上一镜静帧；首镜无额外参考。"""
    prev = _shot(image_ark_url="https://cdn.example.com/shot1.png")
    assert video_extra_refs_for_shot(prev) == ["https://cdn.example.com/shot1.png"]
    assert video_extra_refs_for_shot(None) == []


def test_shot_last_frame_ref_skips_tokenfree_url():
    """TokenFree 尾帧地址不能传给下一镜，退回已发布静帧。"""
    prev = _shot(
        last_frame_url="https://www.tokenfree.com/v1/videos/abc/content",
        image_ark_url="https://cdn.example.com/shot1.png",
    )
    assert shot_last_frame_ref(prev) == "https://cdn.example.com/shot1.png"
    assert video_extra_refs_for_shot(prev) == ["https://cdn.example.com/shot1.png"]


def test_shot_last_frame_ref_prefers_local_still_over_tokenfree_ark():
    """TokenFree ark 静帧跳过，改用本地 /static。"""
    prev = _shot(
        last_frame_url="https://www.tokenfree.com/v1/videos/abc/content",
        image_ark_url="https://www.tokenfree.com/v1/tasks/t1/artifacts/image-0/content",
        image_url="/static/generated/p1/shot_001.png",
    )
    assert shot_last_frame_ref(prev) == "/static/generated/p1/shot_001.png"


def test_persist_last_frame_skips_tokenfree_content_url(monkeypatch):
    """TokenFree /videos/:id/content 不能当 preferred 写回。"""
    monkeypatch.setattr("app.services.storage.local_path_from_url", lambda _url: None)
    out = persist_last_frame_from_video(
        1,
        1,
        "/static/x.mp4",
        preferred_url="https://www.tokenfree.com/v1/videos/abc/content",
    )
    assert out is None


def test_shot_image_ref_skips_tokenfree_and_uses_oss():
    """TokenFree 产物地址不能给上游当参考，改用已发布的公网图。"""
    prev = _shot(
        image_ark_url="https://www.tokenfree.com/v1/tasks/t1/artifacts/image-0/content",
        image_url="https://cdn.example.com/shot1.png",
    )
    assert shot_image_ref(prev) == "https://cdn.example.com/shot1.png"
    refs = image_refs_for_shot(prev, [])
    assert refs == ["https://cdn.example.com/shot1.png"]


def test_previous_usable_shot_skips_empty_middle():
    """中间镜被清空时，后镜参考再往前一镜。"""
    shots = [
        _shot(shot_no=1, image_ark_url="https://cdn.example.com/s1.png"),
        _shot(shot_no=2),
        _shot(shot_no=3, image_ark_url="https://cdn.example.com/s3.png"),
    ]
    prev = previous_usable_shot(shots, 3)
    assert prev is not None
    assert prev.shot_no == 1
    assert previous_shot(shots, 3).shot_no == 2
