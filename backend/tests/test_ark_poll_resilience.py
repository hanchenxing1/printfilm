# -*- coding: utf-8 -*-
"""上游轮询韧性回归：

- fetch_task_once / poll_task 遇到 429、5xx 或单次网络故障时，
  任务状态未知，必须按 running 退避，不能单次误判 failed；
- 400/404 等确定 4xx 仍是终态 failed；
- gen_and_wait_seedance_body 只允许在"参考音频下载失败"时去掉参考音频重提一次，
  隐私拦截/任务失败/超时等异常必须立即上抛，禁止用同 body 重新建单重复计费。
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.services import ark as ark_module
from app.services.ark import (
    ArkGateway,
    TaskResult,
    _is_transient_http_status,
    _retry_after_seconds,
)


class _FakeResponse:
    """最小 httpx.Response 替身：状态码 + JSON 载荷 + 文本 + 响应头。"""

    def __init__(self, status_code: int, payload: dict | None = None, text: str = "err", headers=None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}
        self._payload = payload if payload is not None else {}

    def json(self) -> dict:
        return self._payload


def _install_fake_http(monkeypatch, handler):
    """把 httpx.AsyncClient 替换为按 handler 脚本应答的假客户端，返回 URL 调用记录。"""
    calls: list[str] = []

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, headers=None):
            calls.append(url)
            outcome = handler()
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

    monkeypatch.setattr(ark_module.httpx, "AsyncClient", _FakeAsyncClient)
    return calls


@pytest.fixture
def ark_client(monkeypatch) -> ArkGateway:
    """非 mock、零轮询间隔的客户端（mock 属性会因无渠道 Key 为 True，需显式关掉）。"""
    settings = SimpleNamespace(
        ark_video_poll_timeout=30.0,
        ark_video_poll_interval=0.0,
        ark_base_url="https://ark.cn-beijing.volces.com",
        ark_api_key="test-key",
    )
    client = ArkGateway(settings)
    monkeypatch.setattr(ArkGateway, "mock", property(lambda self: False))
    return client


# ---------- 纯函数 ----------

@pytest.mark.parametrize("code", [429, 500, 502, 503, 504])
def test_transient_status_set(code: int) -> None:
    assert _is_transient_http_status(code)


@pytest.mark.parametrize("code", [200, 400, 401, 403, 404, 409, 422])
def test_terminal_status_not_transient(code: int) -> None:
    assert not _is_transient_http_status(code)


def test_retry_after_seconds_honors_header_and_caps() -> None:
    assert _retry_after_seconds(_FakeResponse(429, headers={"Retry-After": "3"}), 8.0) == 3.0
    assert _retry_after_seconds(_FakeResponse(429, headers={"Retry-After": "120"}), 8.0) == 60.0
    # HTTP-date 形式与缺失时回落默认间隔
    assert _retry_after_seconds(_FakeResponse(429), 8.0) == 8.0
    assert (
        _retry_after_seconds(_FakeResponse(429, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}), 8.0)
        == 8.0
    )


# ---------- fetch_task_once ----------

@pytest.mark.parametrize("code", [429, 500, 502, 503, 504])
async def test_fetch_once_transient_http_treated_running(ark_client, monkeypatch, code: int) -> None:
    _install_fake_http(monkeypatch, lambda: _FakeResponse(code, text="upstream busy"))
    result = await ark_client.fetch_task_once("task-abc")
    assert result.status == "running"
    assert result.provider_task_id == "task-abc"
    assert not result.error


@pytest.mark.parametrize("code", [400, 404])
async def test_fetch_once_terminal_4xx_is_failed(ark_client, monkeypatch, code: int) -> None:
    _install_fake_http(monkeypatch, lambda: _FakeResponse(code, text="task gone"))
    result = await ark_client.fetch_task_once("task-abc")
    assert result.status == "failed"
    assert result.error == "task gone"


async def test_fetch_once_network_error_treated_running(ark_client, monkeypatch) -> None:
    _install_fake_http(monkeypatch, lambda: httpx.ConnectError("connection reset"))
    result = await ark_client.fetch_task_once("task-abc")
    assert result.status == "running"
    assert result.provider_task_id == "task-abc"


async def test_fetch_once_succeeded_passthrough(ark_client, monkeypatch) -> None:
    payload = {
        "id": "task-abc",
        "status": "succeeded",
        "content": {"video_url": "https://cdn.example.com/v.mp4"},
    }
    _install_fake_http(monkeypatch, lambda: _FakeResponse(200, payload=payload))
    result = await ark_client.fetch_task_once("task-abc")
    assert result.status == "succeeded"
    assert result.url == "https://cdn.example.com/v.mp4"


# ---------- poll_task 长轮询 ----------

async def test_poll_retries_after_503_then_succeeds(ark_client, monkeypatch) -> None:
    responses = iter(
        [
            _FakeResponse(503, text="gateway"),
            _FakeResponse(
                200,
                payload={
                    "id": "task-abc",
                    "status": "succeeded",
                    "content": {"video_url": "https://cdn.example.com/v.mp4"},
                },
            ),
        ]
    )
    calls = _install_fake_http(monkeypatch, lambda: next(responses))
    result = await ark_client.poll_task("task-abc")
    assert result.status == "succeeded"
    assert len(calls) == 2


async def test_poll_persistent_429_ends_in_poll_timeout(ark_client, monkeypatch) -> None:
    # 0.05s 总超时 + interval=0：持续 429 必须被 deadline 收敛，而不是首轮判 failed
    ark_client.settings.ark_video_poll_timeout = 0.05
    calls = _install_fake_http(monkeypatch, lambda: _FakeResponse(429, text="rate limited"))
    result = await ark_client.poll_task("task-abc")
    assert result.status == "failed"
    assert result.error == "poll timeout"
    assert len(calls) >= 2


async def test_poll_404_fails_immediately_without_retry(ark_client, monkeypatch) -> None:
    calls = _install_fake_http(monkeypatch, lambda: _FakeResponse(404, text="task gone"))
    result = await ark_client.poll_task("task-abc")
    assert result.status == "failed"
    assert result.error == "task gone"
    assert len(calls) == 1


# ---------- gen_and_wait_seedance_body 重试收窄 ----------

def _audio_body() -> dict:
    return {
        "content": [
            {"type": "text", "text": "镜头画面：星空\n参考音频：素材一\n角色音色：旁白A"},
            {"type": "audio_url", "role": "reference_audio", "audio_url": "https://x/a.mp3"},
        ]
    }


_AUDIO_ERR = 'upstream failure: audio_url resource download failed at task start'
_OK_RESULT = ("/static/x.mp4", None, TaskResult(status="succeeded", url="https://x/v.mp4"))


@pytest.fixture
def seedance_client() -> ArkGateway:
    return ArkGateway(SimpleNamespace())


async def test_seedance_wait_failure_does_not_recreate_task(seedance_client) -> None:
    """等待阶段的非音频错误（如隐私拦截）必须立即上抛，只建过一次单。"""
    seedance_client.gen_video_seedance_body = AsyncMock(return_value="t1")
    seedance_client.wait_video_assets = AsyncMock(side_effect=RuntimeError("privacy blocked"))
    with pytest.raises(RuntimeError, match="privacy blocked"):
        await seedance_client.gen_and_wait_seedance_body(
            _audio_body(), project_id=1, shot_no=2
        )
    seedance_client.gen_video_seedance_body.assert_awaited_once()


async def test_seedance_submit_failure_does_not_recreate_task(seedance_client) -> None:
    """提交阶段的非音频错误立即上抛，不进入第二次建单。"""
    seedance_client.gen_video_seedance_body = AsyncMock(
        side_effect=RuntimeError("400 InvalidParameter: bad body")
    )
    seedance_client.wait_video_assets = AsyncMock()
    with pytest.raises(RuntimeError, match="InvalidParameter"):
        await seedance_client.gen_and_wait_seedance_body(
            _audio_body(), project_id=1, shot_no=2
        )
    seedance_client.gen_video_seedance_body.assert_awaited_once()
    seedance_client.wait_video_assets.assert_not_awaited()


async def test_seedance_wait_audio_error_retries_once_without_audio(seedance_client) -> None:
    """等待阶段报参考音频下载失败：剥离 reference_audio 重提一次并成功。"""
    gen_mock = AsyncMock(side_effect=["t1", "t2"])
    seedance_client.gen_video_seedance_body = gen_mock
    seedance_client.wait_video_assets = AsyncMock(
        side_effect=[RuntimeError(_AUDIO_ERR), _OK_RESULT]
    )
    video_url, _last, result = await seedance_client.gen_and_wait_seedance_body(
        _audio_body(), project_id=1, shot_no=2
    )
    assert video_url == "/static/x.mp4"
    assert result.status == "succeeded"
    assert gen_mock.await_count == 2
    second_body = gen_mock.await_args_list[1].args[0]
    assert not any(
        item.get("type") == "audio_url" and item.get("role") == "reference_audio"
        for item in second_body["content"]
        if isinstance(item, dict)
    )


async def test_seedance_submit_audio_error_retries_once(seedance_client) -> None:
    """提交阶段报参考音频下载失败：剥离后重提一次，随后等待成功。"""
    gen_mock = AsyncMock(side_effect=[RuntimeError(_AUDIO_ERR), "t2"])
    seedance_client.gen_video_seedance_body = gen_mock
    seedance_client.wait_video_assets = AsyncMock(return_value=_OK_RESULT)
    await seedance_client.gen_and_wait_seedance_body(_audio_body(), project_id=1, shot_no=2)
    assert gen_mock.await_count == 2
    seedance_client.wait_video_assets.assert_awaited_once()


async def test_seedance_audio_fallback_used_no_third_submit(seedance_client) -> None:
    """剥离参考音频后仍然失败：最多两次建单，绝无第三次。"""
    gen_mock = AsyncMock(side_effect=[RuntimeError(_AUDIO_ERR), RuntimeError(_AUDIO_ERR)])
    seedance_client.gen_video_seedance_body = gen_mock
    seedance_client.wait_video_assets = AsyncMock(side_effect=RuntimeError(_AUDIO_ERR))
    with pytest.raises(RuntimeError, match="resource download failed"):
        await seedance_client.gen_and_wait_seedance_body(
            _audio_body(), project_id=1, shot_no=2, max_attempts=2
        )
    assert gen_mock.await_count == 2
