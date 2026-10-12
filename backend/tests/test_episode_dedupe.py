"""分集集号去重：剧本列表与保留评分。"""

from types import SimpleNamespace

from app.services.drama.seed import _dedupe_episode_body_items, _episode_keep_score


def test_dedupe_episode_body_items_keeps_last_same_number():
    rows = _dedupe_episode_body_items(
        [
            {"episodeNumber": 1, "title": "旧", "body": "a"},
            {"episodeNumber": 1, "title": "新", "body": "b"},
            {"episodeNumber": 2, "title": "二", "body": "c"},
        ]
    )
    assert len(rows) == 2
    assert rows[0]["title"] == "新"
    assert rows[1]["episodeNumber"] == 2


def test_dedupe_episode_body_items_assigns_missing_numbers():
    rows = _dedupe_episode_body_items(
        [
            {"title": "无号甲", "body": "a"},
            {"episodeNumber": 1, "title": "已有1", "body": "b"},
            {"title": "无号乙", "body": "c"},
        ]
    )
    numbers = [r["episodeNumber"] for r in rows]
    assert numbers == sorted(numbers)
    assert len(set(numbers)) == 3
    assert 1 in numbers


def test_episode_keep_score_prefers_more_videos():
    weak = SimpleNamespace(
        id=1,
        fragments=[SimpleNamespace(video=""), SimpleNamespace(video="")],
    )
    strong = SimpleNamespace(
        id=9,
        fragments=[SimpleNamespace(video="https://x/a.mp4"), SimpleNamespace(video="")],
    )
    assert _episode_keep_score(strong) > _episode_keep_score(weak)
