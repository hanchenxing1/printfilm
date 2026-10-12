"""TokenFree / New API 额度换算与日用量聚合。"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.config import get_settings
from app.services.billing.display import resolve_billing_basis
from app.services.billing.pricing import parse_upstream_cost_fen
from app.services.tokenfree_gateway import tokenfree_site_origin
from app.services.tokenfree_usage import (
    aggregate_quota_data_by_day,
    billing_usage_to_cost_fen,
    fetch_tokenfree_account,
    quota_to_cost_fen,
    usage_dates_are_ignored,
    used_quota_from_raw_json,
)


def test_tokenfree_site_origin_strips_v1():
    assert tokenfree_site_origin("https://www.tokenfree.com/v1") == "https://www.tokenfree.com"
    assert tokenfree_site_origin("https://www.tokenfree.com/v1/") == "https://www.tokenfree.com"


def test_quota_to_cost_fen_one_usd():
    settings = get_settings()
    settings.billing_usd_cny = 7.0
    assert quota_to_cost_fen(500_000, settings) == 700
    assert quota_to_cost_fen(0, settings) == 0


def test_billing_usage_to_cost_fen_one_usd():
    settings = get_settings()
    settings.billing_usd_cny = 7.0
    # OpenAI 兼容 total_usage 单位是 0.01 USD，100 = $1
    assert billing_usage_to_cost_fen(100, settings) == 700


def test_usage_dates_are_ignored_when_values_match():
    assert usage_dates_are_ignored(1200.0, 1200.0, 1200.0) is True
    assert usage_dates_are_ignored(10.0, 20.0, 30.0) is False
    assert usage_dates_are_ignored(0.0, 0.0, 0.0) is False


def test_aggregate_quota_data_by_day():
    settings = get_settings()
    settings.billing_usd_cny = 7.0
    day_ts = int(datetime(2026, 9, 10, tzinfo=UTC).timestamp())
    items = [
        {"created_at": day_ts, "quota": 250_000, "prompt_tokens": 10, "completion_tokens": 5},
        {"date": "2026-09-10", "quota": 250_000, "token_used": 20},
    ]
    daily = aggregate_quota_data_by_day(items, settings)
    assert daily["2026-09-10"]["quota"] == 500_000
    assert daily["2026-09-10"]["cost_fen"] == 700


def test_used_quota_from_raw_json():
    assert used_quota_from_raw_json('{"used_quota": 123}') == 123
    assert used_quota_from_raw_json("not-json") is None


def test_parse_upstream_cost_fen_from_newapi_quota():
    settings = get_settings()
    settings.billing_usd_cny = 7.0
    assert parse_upstream_cost_fen({"usage": {"quota_consumed": 500_000}}, settings) == 700
    assert parse_upstream_cost_fen(
        {"usage": {"prompt_tokens": 1, "quota": 500_000}},
        settings,
    ) == 700
    assert parse_upstream_cost_fen({"prompt_tokens": 1, "quota": 500_000}, settings) == 700
    assert parse_upstream_cost_fen({"quota": 500_000}, settings) is None


def test_pick_migratable_api_key_skips_moonshot_and_ark():
    """启动迁 Key 时不要把 Moonshot/方舟 Key 写进 TokenFree。"""
    from app.schemas_routing import SystemModelChannel
    from app.services.tokenfree_gateway import pick_migratable_api_key

    moonshot = SystemModelChannel(
        id="openai-default",
        name="Moonshot",
        base_url="https://api.moonshot.cn/v1",
        api_key="sk-moonshot",
    )
    ark = SystemModelChannel(
        id="ark-default",
        name="Ark",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        api_key="ark-key",
    )
    assert pick_migratable_api_key([moonshot, ark]) == ""
    tokenfree = SystemModelChannel(
        id="tokenfree",
        name="TokenFree",
        base_url="https://www.tokenfree.com/v1",
        api_key="sk-tokenfree",
    )
    assert pick_migratable_api_key([moonshot, tokenfree]) == "sk-tokenfree"
    aliased = SystemModelChannel(
        id="legacy-openai",
        name="TF",
        base_url="https://www.tokenfree.com/v1",
        api_key="sk-from-url",
    )
    assert pick_migratable_api_key([moonshot, aliased]) == "sk-from-url"


def test_parse_upstream_cost_fen_prefers_quota_over_usd_cost():
    """New API 的 cost 是美元；与 quota 同时出现时按 quota，避免 0.625 被当成 63 分。"""
    settings = get_settings()
    settings.billing_usd_cny = 7.0
    # 0.625 USD × 500000 quota/USD = 312500 quota → ¥4.375 → 438 分
    assert parse_upstream_cost_fen(
        {"usage": {"prompt_tokens": 1, "quota": 312_500, "cost": 0.625}},
        settings,
    ) == 438
    # 无 quota 字段时仍把火山 cost 当人民币元
    assert parse_upstream_cost_fen({"usage": {"cost": 1.23}}, settings) == 123


def test_resolve_billing_basis_newapi_quota():
    raw = '{"usage": {"prompt_tokens": 10, "quota": 500000}}'
    assert resolve_billing_basis(estimated=False, raw_usage_json=raw) == "upstream_cost"


@pytest.mark.asyncio
async def test_fetch_tokenfree_account_prefers_self_when_dashboard_missing(monkeypatch: pytest.MonkeyPatch):
    async def fake_get(path: str, *, params: dict | None = None):
        if path.endswith("/api/user/self"):
            return {"success": True, "data": {"quota": 500_000, "used_quota": 0}}
        return None

    monkeypatch.setattr("app.services.tokenfree_usage._try_tokenfree_get", fake_get)
    settings = get_settings()
    settings.billing_usd_cny = 7.0
    account = await fetch_tokenfree_account(settings)
    assert account["quota"] == 500_000
    assert account["remain_fen"] == 700


@pytest.mark.asyncio
async def test_fetch_tokenfree_account_from_dashboard_usage(monkeypatch: pytest.MonkeyPatch):
    async def fake_get(path: str, *, params: dict | None = None):
        if path.endswith("/subscription"):
            return {"hard_limit_usd": 2.0}
        if "billing/usage" in path:
            return {"total_usage": 100}
        return None

    monkeypatch.setattr("app.services.tokenfree_usage._try_tokenfree_get", fake_get)
    settings = get_settings()
    settings.billing_usd_cny = 7.0
    account = await fetch_tokenfree_account(settings)
    assert account["used_usd"] == 1.0
    assert account["quota"] == 500_000
    assert account["remain_fen"] == 700
