"""摘要完成后自动剧名解析。"""

from app.services.drama.agents import normalize_series_title, pick_auto_project_title


def test_normalize_series_title_strips_quotes_and_length():
    assert normalize_series_title("《月亮跟着我》") == "月亮跟着我"
    assert normalize_series_title("「天空为何蓝」") == "天空为何蓝"
    long = "这是一个非常非常非常非常非常非常长的剧名不应该整段塞进项目标题栏"
    assert len(normalize_series_title(long)) <= 24


def test_pick_auto_project_title_prefers_series_title_over_one_line():
    summary = {
        "seriesTitle": "月亮跟着我",
        "oneLineStory": "小宇发现月亮总跟着自己，和米米一起找波波问为什么。",
    }
    creative = "儿童科普：为什么月亮总是跟着我走路？"
    title = pick_auto_project_title(
        summary,
        creative=creative,
        current_title=creative[:40] + "…",
    )
    assert title == "月亮跟着我"


def test_pick_auto_project_title_skips_when_user_renamed():
    summary = {"seriesTitle": "月亮跟着我"}
    title = pick_auto_project_title(
        summary,
        creative="随便一段创意文案足够长用来测试",
        current_title="我手改的剧名",
    )
    assert title is None
