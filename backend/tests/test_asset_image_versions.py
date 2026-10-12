"""资产生图版本归档与还原。"""

from pathlib import Path
from types import SimpleNamespace

from app.services.drama.generation import (
    activate_asset_image_version,
    archive_asset_image_version,
)


def _asset(**kwargs):
    return SimpleNamespace(**kwargs)


def test_archive_and_activate_asset_image_version(tmp_path, monkeypatch):
    from app.services.drama import generation as gen_mod

    image_file = tmp_path / "asset_1.png"
    image_file.write_bytes(b"old-image")

    def fake_local_path(url: str):
        name = str(url).rsplit("/", 1)[-1]
        path = tmp_path / name
        return path if path.exists() else None

    def fake_rel(path: Path) -> str:
        return f"/static/generated/t/{path.name}"

    def fake_republish(url: str | None, *, sync: bool = True):
        return url

    monkeypatch.setattr("app.services.storage.local_path_from_url", fake_local_path)
    monkeypatch.setattr("app.services.storage.rel_static_url", fake_rel)
    monkeypatch.setattr("app.services.storage.republish_url", fake_republish)

    asset = _asset(
        id=3,
        cover="/static/generated/t/asset_1.png",
        url="/static/generated/t/asset_1.png",
        params={"visualPrompt": "透明小飞船", "image_versions": []},
    )
    archived = archive_asset_image_version(asset, source="generate")  # type: ignore[arg-type]
    assert archived is not None
    hist = asset.params["image_versions"][0]["url"]
    assert "_hist_" in hist
    assert (tmp_path / hist.rsplit("/", 1)[-1]).exists()

    asset.cover = "https://cdn/new.png"
    asset.url = "https://cdn/new.png"
    version_id = asset.params["image_versions"][0]["id"]
    out = activate_asset_image_version(asset, version_id)  # type: ignore[arg-type]
    assert out["cover"] == hist or "_hist_" in out["cover"]
    assert asset.cover == out["cover"]
    assert asset.url == out["cover"]
    assert len(asset.params["image_versions"]) >= 1


def test_archive_skips_empty_image():
    asset = _asset(id=1, cover="", url="", params={})
    assert archive_asset_image_version(asset) is None  # type: ignore[arg-type]


def test_snapshot_downloads_remote_when_local_missing(tmp_path, monkeypatch):
    class FakeResp:
        content = b"remote-bytes"

        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url):
            assert url.startswith("https://")
            return FakeResp()

    monkeypatch.setattr("app.services.storage.STATIC_ROOT", tmp_path)
    monkeypatch.setattr("app.services.storage.local_path_from_url", lambda url: None)
    monkeypatch.setattr(
        "app.services.storage.rel_static_url",
        lambda p: f"/static/{p.relative_to(tmp_path).as_posix()}",
    )
    monkeypatch.setattr("app.services.storage.republish_url", lambda url, sync=True: url)
    monkeypatch.setattr("httpx.Client", FakeClient)

    from app.services.drama.generation import _snapshot_version_media_url

    out = _snapshot_version_media_url("https://cdn.example/asset.png", label="abc")
    assert "_hist_" in out
    hist = tmp_path / "generated" / "_hist" / "asset_hist_abc.png"
    assert hist.exists()
    assert hist.read_bytes() == b"remote-bytes"
