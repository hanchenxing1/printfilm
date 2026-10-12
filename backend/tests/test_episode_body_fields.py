"""分集三分栏 merge / normalize。"""

from app.services.drama.agents import merge_episode_bodies, _normalize_batch_episodes


def test_merge_preserves_creative_and_summary():
    existing = [
        {
            "episodeNumber": 1,
            "title": "开篇",
            "creative": "旧创意",
            "summary": "旧摘要",
            "body": "旧正文" * 20,
        }
    ]
    batch = [
        {
            "episodeNumber": 1,
            "title": "开篇",
            "creative": "新创意更长一些用于覆盖",
            "summary": "新摘要更长一些用于覆盖旧摘要",
            "body": "新正文",
        }
    ]
    merged = merge_episode_bodies(existing, batch, prefer_incoming=True)
    assert len(merged) == 1
    assert merged[0]["creative"].startswith("新创意")
    assert merged[0]["summary"].startswith("新摘要")
    assert merged[0]["body"] == "新正文"


def test_normalize_batch_keeps_creative_summary():
    rows = _normalize_batch_episodes(
        [
            {
                "episodeNumber": 2,
                "title": "月亮",
                "creative": "跟月",
                "summary": "解释视差",
                "content": "正文内容足够长" * 30,
            }
        ],
        2,
        2,
        {2: "月亮"},
    )
    assert len(rows) == 1
    assert rows[0]["creative"] == "跟月"
    assert rows[0]["summary"] == "解释视差"
    assert "正文" in rows[0]["body"]


def test_merge_legacy_body_only_keeps_body_when_incoming_empty():
    """旧数据仅有 body：空 creative/summary 的入站合并不抹掉正文。"""
    existing = [
        {
            "episodeNumber": 1,
            "title": "旧集",
            "body": "只有正文的老数据" * 40,
        }
    ]
    incoming = [
        {
            "episodeNumber": 1,
            "title": "旧集",
            "creative": "补写的本集原始创意内容足够长",
            "summary": "补写的剧情摘要也需要足够长一点才合理",
            "body": "",
        }
    ]
    merged = merge_episode_bodies(existing, incoming, prefer_incoming=True)
    assert merged[0]["body"].startswith("只有正文")
    assert "补写" in merged[0]["creative"]
    assert "补写" in merged[0]["summary"]
