"""确认分集：正文校验与保护分镜不重切。"""

from types import SimpleNamespace

from app.services.drama.agents import MIN_EPISODE_CONTENT_CHARS
from app.services.drama.seed import (
    _episode_should_replace_fragments,
    require_confirmable_episode_body,
)


def test_require_confirmable_episode_body_ok():
    item = require_confirmable_episode_body(
        {
            "episodes": [
                {"episodeNumber": 1, "title": "开篇", "body": "甲" * MIN_EPISODE_CONTENT_CHARS},
                {"episodeNumber": 2, "title": "第 2 集", "body": "", "origin": "manual"},
            ]
        },
        1,
    )
    assert item["title"] == "开篇"


def test_require_confirmable_episode_body_missing():
    try:
        require_confirmable_episode_body({"episodes": [{"episodeNumber": 1, "body": "甲" * 600}]}, 2)
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "找不到" in str(exc)


def test_require_confirmable_episode_body_too_short():
    try:
        require_confirmable_episode_body(
            {"episodes": [{"episodeNumber": 2, "title": "待输入", "body": "太短了"}]},
            2,
        )
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "过短" in str(exc)


def test_protected_video_fragments_are_not_replaced():
    frag = SimpleNamespace(
        video="https://cdn.example/a.mp4",
        content="角色对视。\n【字幕：你好】\n@duration:5",
        params={},
    )
    episode = SimpleNamespace(fragments=[frag], params={})
    assert _episode_should_replace_fragments(episode, "甲" * MIN_EPISODE_CONTENT_CHARS) is False


# 手写电影感分镜没有【字幕：】/@duration:，不能当成场记原文整集重切
def test_protected_cinematic_fragments_are_not_replaced_as_raw():
    frag = SimpleNamespace(
        video="https://cdn.example/a.mp4",
        content="【转入｜无｜片头直接黑起】\n【BGM｜低频太鼓】\n【场景】夜 · 内 · 大牢",
        params={"user_edited": True},
    )
    episode = SimpleNamespace(fragments=[frag], params={})
    assert _episode_should_replace_fragments(episode, "甲" * MIN_EPISODE_CONTENT_CHARS) is False


# 未打 user_edited、也无成片的手写分镜，只要不是场记原文就不要自动重切
def test_unprotected_cinematic_fragments_are_not_auto_replaced():
    frags = [
        SimpleNamespace(
            video="",
            content="【转入｜无｜片头直接黑起】\n【BGM｜低频太鼓】",
            params={},
        ),
        SimpleNamespace(
            video="",
            content="【场景】夜 · 内 · 御史台大牢\n苏轼环顾。",
            params={},
        ),
    ]
    episode = SimpleNamespace(fragments=frags, params={})
    assert _episode_should_replace_fragments(episode, "甲" * MIN_EPISODE_CONTENT_CHARS) is False


# 手写分镜旁夹一条空镜，不能 any() 一条原文就整集重切
def test_mixed_cinematic_and_empty_fragment_is_not_auto_replaced():
    frags = [
        SimpleNamespace(video="", content="【场景】夜 · 内 · 大牢", params={}),
        SimpleNamespace(video="", content="", params={}),
    ]
    episode = SimpleNamespace(fragments=frags, params={})
    assert _episode_should_replace_fragments(episode, "甲" * MIN_EPISODE_CONTENT_CHARS) is False
