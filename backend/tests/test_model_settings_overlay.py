# -*- coding: utf-8 -*-
"""管理端模型配置 overlay 回归：

后台「清除密钥」会在 DB flat 中写入空串。空串是显式清空信号，
_refresh_overlay 必须保留它；否则 get_settings() 会回落 .env 旧密钥，
造成界面显示已清除、上游请求仍携带旧 Key 的危险不一致。
"""
from __future__ import annotations

import pytest

from app import config as config_module
from app.services import model_settings


@pytest.fixture(autouse=True)
def _isolate_overlay() -> None:
    """每个用例后还原全局 overlay 并清 settings 缓存，避免污染其他测试。"""
    saved = dict(model_settings._overlay)
    yield
    model_settings._overlay.clear()
    model_settings._overlay.update(saved)
    config_module.get_settings.cache_clear()


def test_refresh_overlay_keeps_empty_string_secret() -> None:
    model_settings._refresh_overlay(
        {"flat": {"ark_api_key": "", "model_llm": "doubao-test"}}
    )
    overlay = model_settings.get_overlay_dict()
    assert "ark_api_key" in overlay
    assert overlay["ark_api_key"] == ""
    assert overlay["model_llm"] == "doubao-test"


def test_refresh_overlay_skips_only_none() -> None:
    model_settings._refresh_overlay(
        {"flat": {"ark_api_key": None, "model_llm": "doubao-test"}}
    )
    overlay = model_settings.get_overlay_dict()
    assert "ark_api_key" not in overlay
    assert overlay["model_llm"] == "doubao-test"


def test_cleared_secret_overrides_env_value(monkeypatch: pytest.MonkeyPatch) -> None:
    """env/.env 中存在旧密钥时，overlay 空串必须真正把它清空。"""
    monkeypatch.setenv("ARK_API_KEY", "env-old-secret")
    config_module.get_settings.cache_clear()
    assert config_module.get_settings().ark_api_key == "env-old-secret"

    model_settings._refresh_overlay({"flat": {"ark_api_key": ""}})
    config_module.get_settings.cache_clear()
    assert config_module.get_settings().ark_api_key == ""


def test_unset_secret_falls_back_to_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """overlay 不含该字段（None 被跳过）时仍正常回落 env 配置。"""
    monkeypatch.setenv("ARK_API_KEY", "env-live-key")
    model_settings._refresh_overlay({"flat": {"ark_api_key": None, "model_llm": "x"}})
    config_module.get_settings.cache_clear()
    assert config_module.get_settings().ark_api_key == "env-live-key"
