"""用户点名的图模型不要被静默换成同能力的 Seedream。"""

from app.schemas_routing import (
    DefaultModels,
    LogicalModel,
    LogicalModelBinding,
    SystemModelChannel,
)
from app.services.logical_model_router import resolve_logical_model
from app.services.model_settings import _refresh_routing_snapshot, get_routing_snapshot


def test_requested_gpt_image_keeps_upstream():
    prev = get_routing_snapshot()
    channel = SystemModelChannel(
        id="tokenfree",
        name="TokenFree",
        base_url="https://www.tokenfree.com/v1",
        api_key="sk-test",
        has_api_key=True,
        protocol="openai",
        models=["gpt-image-2-5", "seedream-5-0-pro"],
        enabled=True,
    )
    # gpt-image 逻辑模型绑定坏了时，仍应按渠道清单直连
    seedream = LogicalModel(
        id="seedream-5.0",
        capability="image",
        enabled=True,
        bindings=[
            LogicalModelBinding(channel_id="tokenfree", upstream_model="seedream-5-0-pro", enabled=True)
        ],
    )
    try:
        _refresh_routing_snapshot([channel], [seedream], DefaultModels(image_model="seedream-5.0"))
        route = resolve_logical_model("image", "gpt-image-2-5")
        assert route is not None
        assert route.upstream_model == "gpt-image-2-5"
    finally:
        _refresh_routing_snapshot(prev.channels, prev.logical_models, prev.default_models)
