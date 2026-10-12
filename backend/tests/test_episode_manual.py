"""手动加集：自动流水线跳过空集，合并时保留 origin。"""

from app.services.drama.agents import (
    MAX_DRAMA_EPISODES,
    append_manual_episode,
    auto_missing_episode_numbers,
    merge_episode_bodies,
)


def test_auto_missing_skips_manual_empty():
    existing = [
        {"episodeNumber": 1, "title": "天空为何蓝", "body": "甲" * 500},
        {"episodeNumber": 2, "title": "第 2 集", "body": "", "origin": "manual"},
    ]
    assert auto_missing_episode_numbers(existing, 2) == []


def test_auto_missing_fills_auto_empty():
    existing = [{"episodeNumber": 1, "title": "第 1 集", "body": ""}]
    assert auto_missing_episode_numbers(existing, 2) == [1, 2]


def test_auto_missing_fills_gap_without_row():
    existing = [{"episodeNumber": 1, "title": "开篇", "body": "乙" * 500}]
    assert auto_missing_episode_numbers(existing, 3) == [2, 3]


def test_merge_preserves_manual_origin():
    existing = [
        {
            "episodeNumber": 2,
            "title": "第 2 集",
            "body": "短草稿",
            "origin": "manual",
        }
    ]
    batch = [{"episodeNumber": 2, "title": "追光", "body": "丙" * 80}]
    merged = merge_episode_bodies(existing, batch)
    assert merged[0]["origin"] == "manual"
    assert merged[0]["title"] == "追光"


def test_merge_prefer_incoming_replaces_longer_draft():
    existing = [
        {
            "episodeNumber": 2,
            "title": "第 2 集",
            "body": "用户很长的草稿" * 20,
            "origin": "manual",
        }
    ]
    batch = [{"episodeNumber": 2, "title": "优化后", "body": "短正文"}]
    merged = merge_episode_bodies(existing, batch, prefer_incoming=True)
    assert merged[0]["body"] == "短正文"
    assert merged[0]["origin"] == "manual"


def test_append_manual_episode_increments():
    existing = [{"episodeNumber": 1, "title": "天空为何蓝", "body": "丁" * 40}]
    episodes, number = append_manual_episode(existing)
    assert number == 2
    assert episodes[-1]["origin"] == "manual"
    assert episodes[-1]["body"] == ""
    assert episodes[-1]["title"] == "第 2 集"


def test_append_manual_episode_respects_max():
    existing = [{"episodeNumber": MAX_DRAMA_EPISODES, "title": "终章", "body": ""}]
    try:
        append_manual_episode(existing)
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "最多" in str(exc)
