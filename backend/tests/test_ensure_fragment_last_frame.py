"""成片缺尾帧时补抽 / 读取回退。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.services.drama.generation import (
    ensure_fragment_last_frame_url,
    read_fragment_last_frame_url,
    write_fragment_last_frame_url,
)


def test_read_fragment_last_frame_from_generation_block():
    frag = SimpleNamespace(
        params={"generation": {"status": "done", "lastFrameUrl": "/static/a_last.jpg"}},
        video="/static/a.mp4",
    )
    assert read_fragment_last_frame_url(frag) == "/static/a_last.jpg"


def test_write_fragment_last_frame_mirrors_generation():
    frag = SimpleNamespace(params={"generation": {"status": "done"}}, video="/static/a.mp4")
    write_fragment_last_frame_url(frag, "/static/b_last.jpg")
    assert frag.params["lastFrameUrl"] == "/static/b_last.jpg"
    assert frag.params["generation"]["lastFrameUrl"] == "/static/b_last.jpg"


@pytest.mark.asyncio
async def test_ensure_extracts_when_video_ready(tmp_path):
    video = tmp_path / "shot.mp4"
    video.write_bytes(b"fake")
    project = SimpleNamespace(id=1)
    frag = SimpleNamespace(
        id=9,
        params={"generation": {"status": "done"}},
        video=str(video),
    )

    with (
        patch("app.services.storage.local_path_from_url", return_value=video),
        patch("app.services.storage.project_dir", return_value=tmp_path),
        patch("app.services.storage.rel_static_url", return_value="/static/last.jpg"),
        patch("app.services.storage.republish_url", side_effect=lambda u, sync=True: u),
        patch(
            "app.services.ffmpeg_compose.extract_video_last_frame",
            side_effect=lambda _src, dest: dest.write_bytes(b"jpg") or True,
        ) as extract,
    ):
        url = await ensure_fragment_last_frame_url(project, frag)

    assert url == "/static/last.jpg"
    assert frag.params["lastFrameUrl"] == "/static/last.jpg"
    extract.assert_called_once()
