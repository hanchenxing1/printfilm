"""内置漫剧画面风格 ID / 文案保持对齐。"""

from app.services.drama.generation_prompt import append_style_prompt, build_generation_prompt
from app.services.drama.image_styles import (
    IMAGE_STYLE_IDS,
    IMAGE_STYLE_LABELS,
    IMAGE_STYLE_PROMPTS,
    STYLE_BOARD_PROMPT_HINT,
    _board_fail_cache,
    _board_url_cache,
    append_style_board_url,
    resolve_image_style_board_url,
    resolve_image_style_prompt,
    style_board_local_path,
)
from app.services.style_lock import seedream_ref_urls, split_seedream_subject_style_refs


def test_image_style_catalog_is_aligned():
    assert set(IMAGE_STYLE_IDS) == set(IMAGE_STYLE_LABELS)
    assert set(IMAGE_STYLE_IDS) == set(IMAGE_STYLE_PROMPTS)


def test_ghibli_handdrawn_style_resolves():
    prompt = resolve_image_style_prompt("ghibli-handdrawn-anime")
    assert "水彩" in prompt
    assert "赛璐璐" in prompt
    assert IMAGE_STYLE_LABELS["ghibli-handdrawn-anime"] == "宫崎骏气质手绘"


def test_style_board_prefers_backend_raster_and_skips_svg():
    path = style_board_local_path("palace-intrigue-cold")
    assert path is not None
    assert path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
    ghibli = style_board_local_path("ghibli-handdrawn-anime")
    if ghibli is not None:
        assert ghibli.suffix.lower() != ".svg"


def test_style_board_rejects_unknown_and_path_traversal():
    assert style_board_local_path("../generated/p355") is None
    assert style_board_local_path("..\\generated") is None
    assert style_board_local_path("/etc/passwd") is None
    assert style_board_local_path("palace-intrigue-cold/../../secret") is None
    assert style_board_local_path("not-a-real-style") is None


def test_resolve_image_style_board_url_publishes_https(monkeypatch):
    _board_url_cache.clear()
    _board_fail_cache.clear()
    monkeypatch.setattr(
        "app.services.storage.publish_local",
        lambda path, sync=True: "https://cdn.example.com/style-board.png",
    )
    url = resolve_image_style_board_url("palace-intrigue-cold")
    assert url == "https://cdn.example.com/style-board.png"


def test_resolve_image_style_board_url_skips_localhost(monkeypatch):
    _board_url_cache.clear()
    _board_fail_cache.clear()
    monkeypatch.setattr(
        "app.services.storage.publish_local",
        lambda path, sync=True: "http://127.0.0.1:8000/static/board.png",
    )
    assert resolve_image_style_board_url("palace-intrigue-cold") == ""


def test_append_style_prompt_mentions_style_board():
    text = append_style_prompt("少女站在窗边", "ghibli-handdrawn-anime", has_style_board=True)
    assert STYLE_BOARD_PROMPT_HINT in text
    assert "禁止复制该图的人物" in text
    locked = build_generation_prompt(
        "黑发少女",
        asset_type="character",
        style_id="ghibli-handdrawn-anime",
        has_style_board=True,
    )
    assert STYLE_BOARD_PROMPT_HINT in locked
    plain = append_style_prompt("少女站在窗边", "ghibli-handdrawn-anime", has_style_board=False)
    assert STYLE_BOARD_PROMPT_HINT not in plain


def test_seedream_ref_urls_default_two_drama_split_reserves_style():
    subjects = [f"https://cdn.example.com/c{i}.png" for i in range(8)]
    styles = ["https://cdn.example.com/style.png"]
    assert len(seedream_ref_urls(*subjects)) == 2
    assert len(seedream_ref_urls(*subjects, limit=6)) == 6
    subject_refs, style_refs = split_seedream_subject_style_refs(subjects, styles)
    assert len(subject_refs) == 5
    assert style_refs == styles
    merged = append_style_board_url(subjects, styles[0], max_total=30)
    assert merged[-1] == styles[0]
    assert len(merged) == 9

