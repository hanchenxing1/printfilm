"""Seedance 2 / 2.5 逻辑模型路由。"""

from app.services.drama.build_seedance_generate_body import resolve_seedance_model_endpoint
from app.services.logical_model_router import resolve_upstream_model
from app.services.model_settings import _bootstrap_logical_from_channels, _seedance_logical_meta
from app.services.tokenfree_gateway import locked_tokenfree_channel


def test_seedance_logical_meta_detects_versions():
    assert _seedance_logical_meta("doubao-seedance-2-5-260628") == ("seedance-2.5", "Seedance 2.5")
    assert _seedance_logical_meta("doubao-seedance-2-0-260128") == ("seedance-2", "Seedance 2")
    assert _seedance_logical_meta("seedance-2-0-mini") == ("seedance-2-0-mini", "Seedance 2.0 Mini")


def test_bootstrap_aliases_match_tokenfree_catalog_ids(monkeypatch):
    """渠道已是 TokenFree 目录 id 时，仍能挂上 seedance-2.5 / seedance-2 别名。"""
    from app.config import Settings

    settings = Settings(
        model_llm="kimi-k2.6",
        model_video="doubao-seedance-2-5-260628",
        model_video_2="doubao-seedance-2-0-260128",
        openai_api_key="test-key",
    )
    monkeypatch.setattr("app.services.model_settings.get_settings", lambda: settings)
    monkeypatch.setattr("app.config.get_settings", lambda: settings)

    channels = [
        locked_tokenfree_channel(
            api_key="test-key",
            models=["kimi-k2.6", "seedance-2-5", "seedance-2-0"],
            enabled=True,
        )
    ]
    logical_models, defaults = _bootstrap_logical_from_channels(channels)
    ids = {model.id for model in logical_models if model.capability == "video"}
    assert ids == {"seedance-2.5", "seedance-2"}
    assert defaults.video_model == "seedance-2.5"


def test_bootstrap_registers_seedance_2_and_25(monkeypatch):
    from app.config import Settings

    settings = Settings(
        model_llm="kimi-k2.6",
        model_video="doubao-seedance-2-5-260628",
        model_video_2="doubao-seedance-2-0-260128",
        openai_api_key="test-key",
    )
    monkeypatch.setattr("app.services.model_settings.get_settings", lambda: settings)
    monkeypatch.setattr("app.config.get_settings", lambda: settings)

    channels = [
        locked_tokenfree_channel(
            api_key="test-key",
            models=[settings.model_llm, settings.model_video, settings.model_video_2],
            enabled=True,
        )
    ]
    logical_models, defaults = _bootstrap_logical_from_channels(channels)
    ids = {model.id for model in logical_models if model.capability == "video"}
    assert ids == {"seedance-2.5", "seedance-2"}
    assert "doubao-seedance-2-5-260628" not in ids
    assert defaults.video_model == "seedance-2.5"


def test_resolve_upstream_model_routes_seedance_2(monkeypatch):
    from app.config import Settings
    from app.schemas_routing import DefaultModels, LogicalModel, LogicalModelBinding
    import app.services.model_settings as model_settings

    settings = Settings(
        model_video="doubao-seedance-2-5-260628",
        model_video_2="doubao-seedance-2-0-260128",
    )
    monkeypatch.setattr("app.config.get_settings", lambda: settings)

    snapshot = model_settings.RoutingSnapshot(
        channels=[],
        logical_models=[
            LogicalModel(
                id="seedance-2.5",
                name="Seedance 2.5",
                capability="video",
                enabled=True,
                bindings=[LogicalModelBinding(channel_id="tokenfree", upstream_model=settings.model_video)],
            ),
            LogicalModel(
                id="seedance-2",
                name="Seedance 2",
                capability="video",
                enabled=True,
                bindings=[LogicalModelBinding(channel_id="tokenfree", upstream_model=settings.model_video_2)],
            ),
        ],
        default_models=DefaultModels(video_model="seedance-2.5"),
    )
    monkeypatch.setattr(model_settings, "_routing_snapshot", snapshot)

    assert resolve_upstream_model("video", "seedance-2.5") == settings.model_video
    assert resolve_upstream_model("video", "seedance-2") == settings.model_video_2
    assert resolve_seedance_model_endpoint("seedance-2") == settings.model_video_2
