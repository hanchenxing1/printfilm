"""资产 params 合并与剧名同步回归。"""

from app.api.drama.assets import _merge_asset_params
from app.services.drama.agents import pick_auto_project_title


def test_merge_asset_params_keeps_image_versions_when_client_omits():
    prev = {
        "visualPrompt": "旧提示词",
        "image_versions": [{"id": "img_1", "url": "/static/a.png"}],
        "generation": {"status": "done"},
    }
    incoming = {"visualPrompt": "新提示词", "generation": {"status": "done"}}
    merged = _merge_asset_params(prev, incoming)
    assert merged["visualPrompt"] == "新提示词"
    assert merged["image_versions"] == prev["image_versions"]


def test_merge_asset_params_keeps_generating_status():
    prev = {
        "visualPrompt": "a",
        "generation": {"status": "generating", "queued_at": "x"},
        "image_versions": [{"id": "img_1", "url": "/static/a.png"}],
    }
    incoming = {
        "visualPrompt": "b",
        "generation": {"status": "done"},
        "image_versions": [],
    }
    merged = _merge_asset_params(prev, incoming)
    assert merged["generation"]["status"] == "generating"
    assert len(merged["image_versions"]) == 1


def test_pick_auto_skips_custom_title_like_update_script():
    summary = {"seriesTitle": "月亮跟着我"}
    assert (
        pick_auto_project_title(
            summary,
            creative="儿童科普创意文案足够长",
            current_title="我手改的剧名",
        )
        is None
    )
