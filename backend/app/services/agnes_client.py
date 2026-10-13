"""Agnes AI 异步客户端（httpx）：文本 / 图像 / 视频。

端点契约（Agnes 官方 API，https://www.agnes-ai.com/docs）：
  Base URL     https://apihub.agnes-ai.com/v1
  认证头        Authorization: Bearer <api_key>；Content-Type: application/json
  文本模型      agnes-3.0-flash          POST /v1/chat/completions（OpenAI 兼容）
  图像模型      agnes-image-2.5-flash    POST /v1/images/generations
  视频模型      agnes-video-2.5-flash    POST /v1/videos + GET /agnesapi?video_id=...

与 /_video_submit/agnes_api.py（同步 urllib 版，pri 引擎已验证）同构：
- 多账号 key 池：渠道 api_key 或 AGNES_API_KEYS 逗号分隔；429/401 自动轮换
- 客户端 RPM 节流（对齐官方限额）：text 20 / image_1K-2K 20-10 / 3K-4K 1 / video 1
- 视频 sticky key：提交→轮询→下载固定同一把 key（任务归属账号）
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import mimetypes
import re
import time
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://apihub.agnes-ai.com/v1"
DEFAULT_TEXT_MODEL = "agnes-3.0-flash"
DEFAULT_IMAGE_MODEL = "agnes-image-2.5-flash"
DEFAULT_VIDEO_MODEL = "agnes-video-2.5-flash"

# 客户端侧 RPM 节流（对齐官方 free 池限额，防 429；N 把 key 聚合 N× 吞吐）
_RPM_LIMITS = {
    "text": 20,
    "image_1K": 20,
    "image_2K": 10,
    "image_3K": 1,
    "image_4K": 1,
    "video": 1,
}

_VIDEO_SECONDS_RANGE = (4, 12)


class AgnesError(RuntimeError):
    """Agnes 平台请求 / 解析错误。"""


def _image_rpm_key(size: str | None) -> str:
    s = str(size or "").strip().upper()
    if s in ("1K", "2K", "3K", "4K"):
        return "image_" + s
    m = re.match(r"^(\d+)X(\d+)$", s)
    if m:
        dim = max(int(m.group(1)), int(m.group(2)))
        if dim < 2048:
            return "image_1K"
        if dim < 3072:
            return "image_2K"
        if dim < 4096:
            return "image_3K"
        return "image_4K"
    return "image_1K"


def _short_key(k: str) -> str:
    return (k[:6] + "…" + k[-4:]) if len(k) > 14 else (k or "")[:8]


class AgnesClient:
    """异步 Agnes 客户端：key 池轮转 + RPM 节流 + 429 退避。"""

    def __init__(
        self,
        api_keys: list[str],
        base_url: str = DEFAULT_BASE_URL,
        *,
        text_model: str = DEFAULT_TEXT_MODEL,
        image_model: str = DEFAULT_IMAGE_MODEL,
        video_model: str = DEFAULT_VIDEO_MODEL,
        poll_interval: float = 10.0,
        poll_timeout: float = 1800.0,
        request_timeout: float = 300.0,
    ) -> None:
        if not api_keys:
            raise AgnesError("Agnes 未配置任何 API key")
        self.api_keys = [k.strip() for k in api_keys if k and k.strip()]
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.text_model = text_model or DEFAULT_TEXT_MODEL
        self.image_model = image_model or DEFAULT_IMAGE_MODEL
        self.video_model = video_model or DEFAULT_VIDEO_MODEL
        self.poll_interval = poll_interval
        self.poll_timeout = poll_timeout
        self.request_timeout = request_timeout
        self._bad_keys: set[str] = set()
        self._key_rr = 0
        self._key_lock = asyncio.Lock()
        # (rpm_key, key) → last-timestamp
        self._throttle_last: dict[tuple[str, str], float] = {}
        self._throttle_lock = asyncio.Lock()
        # video_id → sticky key（提交→轮询→下载固定同一账号）
        self._video_keys: dict[str, str] = {}

    # ---------- key 池 ----------

    @property
    def api_key(self) -> str:
        """默认（文本/图像）轮转选 key；sticky 场景请显式传 key。"""
        return self._pick_key_sync()

    def _pick_key_sync(self) -> str:
        n = len(self.api_keys)
        for i in range(n):
            k = self.api_keys[(self._key_rr + i) % n]
            if k not in self._bad_keys:
                self._key_rr = (self._key_rr + i + 1) % n
                return k
        return self.api_keys[0]

    def _mark_bad(self, key: str, reason: str) -> None:
        if key not in self._bad_keys:
            self._bad_keys.add(key)
            logger.warning("[Agnes] key %s 失效（%s），切换到下一账号", _short_key(key), reason)

    async def _throttle(self, rpm_key: str, key: str, label: str = "") -> None:
        rpm = _RPM_LIMITS.get(rpm_key)
        if not rpm or rpm <= 0:
            return
        min_gap = 60.0 / rpm
        async with self._throttle_lock:
            now = time.monotonic()
            last = self._throttle_last.get((rpm_key, key))
            if last is not None:
                wait = last + min_gap - now
                if wait > 0.05:
                    logger.info(
                        "[Agnes] RPM 节流 %s@%s（≥%.0fs/次，%d RPM）等待 %.1fs",
                        label, _short_key(key), min_gap, rpm, wait,
                    )
                    await asyncio.sleep(wait)
            self._throttle_last[(rpm_key, key)] = time.monotonic()

    # ---------- 底层请求 ----------

    async def _post_json(
        self,
        url: str,
        payload: dict[str, Any],
        *,
        key: str,
        timeout: float | None = None,
        retries: int = 2,
        sticky: bool = False,
    ) -> dict[str, Any]:
        """单次 POST；429 非 sticky 时自动换 key，401/403 标坏并切换。"""
        body = json.dumps(payload).encode("utf-8")
        active = key or self._pick_key_sync()
        key_idx = 0
        total = len(self.api_keys) if not sticky else 1
        while True:
            last_err: Exception | None = None
            for i in range(retries + 1):
                try:
                    async with httpx.AsyncClient(timeout=timeout or self.request_timeout) as client:
                        resp = await client.post(
                            url,
                            content=body,
                            headers={
                                "Authorization": f"Bearer {active}",
                                "Content-Type": "application/json",
                            },
                        )
                    try:
                        data = resp.json()
                    except Exception:
                        data = {"raw": resp.text[:500], "status_code": resp.status_code}
                    if resp.status_code >= 400:
                        raise AgnesError(
                            f"云端 HTTP {resp.status_code}（账号 {_short_key(active)}）："
                            f"{json.dumps(data, ensure_ascii=False)[:400]}"
                        )
                    return data
                except AgnesError as e:
                    msg = str(e)
                    last_err = e
                    if "HTTP 429" in msg:
                        if i < retries:
                            await asyncio.sleep(min(5.0 * (2**i), 30.0))
                            continue
                        if not sticky and key_idx + 1 < total and len(self._bad_keys) < len(self.api_keys):
                            key_idx += 1
                            active = self._pick_key_sync()
                            logger.info("[Agnes] 429 换账号 → %s", _short_key(active))
                            break  # 换 key 重开一轮
                        raise
                    if "HTTP 401" in msg or "HTTP 403" in msg:
                        self._mark_bad(active, msg[:80])
                        if not sticky and key_idx + 1 < total and len(self._bad_keys) < len(self.api_keys):
                            key_idx += 1
                            active = self._pick_key_sync()
                            break
                        raise
                    if i < retries:
                        await asyncio.sleep(1.5 * (i + 1))
                        continue
                    raise
                except httpx.HTTPError as e:
                    last_err = e
                    if i < retries:
                        await asyncio.sleep(1.0 * (i + 1))
                        continue
                    raise AgnesError(f"云端 请求失败（账号 {_short_key(active)}）：{e}") from e
            if last_err is None:
                # 换 key 后外层继续
                continue
            raise AgnesError(f"云端 请求重试耗尽：{last_err}")

    # ---------- 文本（OpenAI 兼容；通常走渠道 openai 协议，此方法备用） ----------

    async def chat(
        self,
        prompt: str,
        system: str | None = None,
        temperature: float = 0.6,
        max_tokens: int = 4096,
        model: str | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        msgs: list[dict[str, Any]] = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.append({"role": "user", "content": prompt})
        payload = {
            "model": model or self.text_model,
            "messages": msgs,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            payload["response_format"] = response_format
        key = self._pick_key_sync()
        await self._throttle("text", key, "文本")
        resp = await self._post_json(
            self.base_url + "/chat/completions", payload, key=key, timeout=240.0
        )
        choices = resp.get("choices") or []
        if not choices:
            raise AgnesError(f"云端 文本响应无 choices：{json.dumps(resp, ensure_ascii=False)[:300]}")
        msg = choices[0].get("message") or {}
        content = msg.get("content")
        if content is None:
            content = choices[0].get("text") or ""
        return str(content)

    # ---------- 参考图 → data URI ----------

    @staticmethod
    async def _data_uri_for(path_or_url: str | Path, local_hint: str | None = None) -> str:
        """本地路径 /static URL → Data URI Base64；http(s) 原样返回。"""
        from app.services import storage

        s = str(path_or_url or "").strip()
        if not s:
            return ""
        if s.lower().startswith(("http://", "https://", "data:")):
            return s
        # /static/... 或本地路径
        p: Path | None = None
        if local_hint:
            cand = Path(local_hint)
            if cand.is_file():
                p = cand
        if p is None:
            p = storage.local_path_from_url(s)
        if p is None:
            return s  # 无本地副本，按 URL 传
        if not p.is_file():
            return s
        mime = mimetypes.guess_type(p.name)[0] or "image/png"
        b64 = base64.b64encode(p.read_bytes()).decode("ascii")
        return f"data:{mime};base64,{b64}"

    # ---------- 图像 ----------

    async def generate_image(
        self,
        prompt: str,
        *,
        width: int | None = None,
        height: int | None = None,
        size: str | None = None,
        ratio: str | None = None,
        ref_images: list[str] | None = None,
        local_hints: list[str] | None = None,
        model: str | None = None,
    ) -> bytes:
        """Agnes 生图 → 图像 bytes。size 形如 "2K" 或 "1024x1024"。"""
        if not prompt or not str(prompt).strip():
            raise AgnesError("云端 生图 prompt 为空")
        if width and height:
            eff_size = f"{int(width)}x{int(height)}"
            eff_ratio = ratio or _image_rpm_key(eff_size).replace("image_", "")
        else:
            eff_size = size or "2K"
            eff_ratio = ratio or "16:9"
        refs = []
        for i, r in enumerate(ref_images or []):
            hint = local_hints[i] if local_hints and i < len(local_hints) else None
            d = await self._data_uri_for(r, hint)
            if d:
                refs.append(d)
        extra: dict[str, Any] = {"response_format": "b64_json"}
        if refs:
            extra["image"] = refs[:5]
        payload = {
            "model": model or self.image_model,
            "prompt": str(prompt),
            "size": eff_size,
            "ratio": eff_ratio,
            "extra_body": extra,
        }
        key = self._pick_key_sync()
        rpm = _image_rpm_key(eff_size)
        await self._throttle(rpm, key, f"生图 {str(eff_size).upper()} 档")
        resp = await self._post_json(
            self.base_url + "/images/generations",
            payload,
            key=key,
            timeout=360.0,
        )
        return await self._extract_image_bytes(resp)

    @staticmethod
    async def _extract_image_bytes(resp: dict[str, Any]) -> bytes:
        data = resp.get("data") or []
        if isinstance(data, dict):
            data = [data]
        async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
            for item in data:
                if not isinstance(item, dict):
                    continue
                b64 = item.get("b64_json") or item.get("base64") or ""
                if b64:
                    if b64.startswith("data:"):
                        b64 = b64.split(",", 1)[1]
                    try:
                        return base64.b64decode(b64)
                    except Exception:
                        pass
                u = item.get("url") or ""
                if u:
                    raw = await client.get(u)
                    raw.raise_for_status()
                    return raw.content
            for u in (resp.get("url"), resp.get("image_url")):
                if u:
                    raw = await client.get(u)
                    raw.raise_for_status()
                    return raw.content
        raise AgnesError(
            "云端 生图响应无图片：%s" % json.dumps(resp, ensure_ascii=False)[:300]
        )

    # ---------- 视频 ----------

    @staticmethod
    def _pick_video_mode(
        ref_images: list[str] | None, first_frame: str | None, last_frame: str | None
    ) -> str:
        if first_frame or last_frame:
            return "keyframe"
        if ref_images:
            return "reference"
        return "text"

    async def video_submit(
        self,
        prompt: str,
        *,
        ref_images: list[str] | None = None,
        first_frame: str | None = None,
        last_frame: str | None = None,
        local_hints: list[str] | None = None,
        duration: int = 5,
        ratio: str | None = None,
        model: str | None = None,
    ) -> tuple[str, str]:
        """提交视频任务 → (video_id, sticky_key)。"""
        if not prompt or not str(prompt).strip():
            raise AgnesError("云端 视频 prompt 为空")
        mode = self._pick_video_mode(ref_images, first_frame, last_frame)
        sec = max(_VIDEO_SECONDS_RANGE[0], min(_VIDEO_SECONDS_RANGE[1], int(round(float(duration or 5)))))
        model = model or self.video_model
        payload: dict[str, Any] = {
            "model": model,
            "prompt": str(prompt),
            "mode": mode,
            "seconds": int(sec),
            "size": "720P",
            "aspect_ratio": ratio or "16:9",
            "n": 1,
        }

        async def _to_uri(u: str | None, hint_i: int) -> str:
            hint = local_hints[hint_i] if local_hints and hint_i < len(local_hints) else None
            return await self._data_uri_for(u, hint) if u else ""

        if mode == "keyframe":
            f1 = await _to_uri(first_frame, 0)
            f2 = await _to_uri(last_frame, 1)
            if f1:
                payload["first_frame"] = f1
            if f2:
                payload["last_frame"] = f2
        elif mode == "reference":
            imgs = []
            for i, r in enumerate(ref_images or []):
                d = await _to_uri(r, i)
                if d:
                    imgs.append(d)
            if imgs:
                payload["images"] = imgs[:5]

        sticky = self._pick_key_sync()
        await self._throttle("video", sticky, "视频任务")
        resp = await self._post_json(
            self.base_url + "/videos", payload, key=sticky, sticky=True, timeout=120.0
        )
        video_id = self._extract_video_id(resp)
        # 自描述 task_id：编码 sticky key 下标，重启后也能找回提交账号
        try:
            key_index = self.api_keys.index(sticky)
        except ValueError:
            key_index = 0
        task_id = f"agnes:{key_index}:{video_id}"
        self._video_keys[task_id] = sticky
        self._video_keys[video_id] = sticky
        logger.info(
            "[Agnes] 视频提交 mode=%s %ss ratio=%s 参考=%d 账号=%s task_id=%s",
            mode, sec, payload["aspect_ratio"], len(ref_images or []),
            _short_key(sticky), task_id,
        )
        return task_id, sticky

    @staticmethod
    def _extract_video_id(resp: dict[str, Any]) -> str:
        for k in ("video_id", "id", "task_id"):
            v = resp.get(k) if isinstance(resp, dict) else None
            if v:
                return str(v)
        raise AgnesError("云端 创建视频任务未返回 video_id：%s" % json.dumps(resp, ensure_ascii=False)[:300])

    def _query_url(self) -> str:
        """轮询端点：host 根 /agnesapi（与 /v1 基址无关，仅取 host）。"""
        host = re.sub(r"^https?://", "", self.base_url).split("/")[0]
        return f"https://{host}/agnesapi"

    async def video_poll_once(
        self, video_id: str, model: str, key: str
    ) -> tuple[str, str | None, str | None]:
        """单次轮询 → (status, url, error)。status: running|succeeded|failed。"""
        from urllib.parse import urlencode

        query = urlencode({"video_id": video_id, "model_name": model or self.video_model})
        url = self._query_url() + "?" + query
        try:
            async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
                resp = await client.get(
                    url, headers={"Authorization": f"Bearer {key}"}
                )
            if resp.status_code == 429:
                return "running", None, "rate_limited"
            if resp.status_code >= 400:
                return "failed", None, f"HTTP {resp.status_code}: {resp.text[:200]}"
            data = resp.json()
        except httpx.HTTPError as e:
            return "running", None, f"poll network: {e}"
        if not isinstance(data, dict):
            return "running", None, "poll response not json"
        inner = data.get("data")
        if not isinstance(inner, dict):
            inner = data
        # 状态字段兼容 status / internal_status（实测 agnesapi 返回 internal_status）
        status = str(
            data.get("status") or inner.get("status")
            or data.get("internal_status") or ""
        )
        low = status.lower()
        if low in ("completed", "complete", "succeeded", "success", "done", "finished"):
            for src in (data, inner):
                for k in ("url", "video_url", "output_url", "file_url", "output"):
                    v = src.get(k)
                    if isinstance(v, str) and v.startswith("http"):
                        return "succeeded", v, None
                content = src.get("content")
                if isinstance(content, dict):
                    for k in ("url", "video_url", "output"):
                        v = content.get(k)
                        if isinstance(v, str) and v.startswith("http"):
                            return "succeeded", v, None
            return "failed", None, "视频成功但响应缺少下载链接"
        if low in ("failed", "fail", "error", "cancelled", "canceled"):
            msg = inner.get("error") or inner.get("message") or data.get("error") or status or "failed"
            return "failed", None, str(msg)[:300]
        return "running", None, None

    async def video_wait(
        self, video_id: str, model: str, key: str
    ) -> str:
        """阻塞轮询到成功，返回下载 URL。"""
        start = time.monotonic()
        while True:
            if time.monotonic() - start > self.poll_timeout:
                raise AgnesError(f"云端 视频等待超时（{self.poll_timeout}s），video_id={video_id}")
            # 轮询端点不计入生成 RPM；429 由 video_poll_once 按 running 容错
            status, url, err = await self.video_poll_once(video_id, model, key)
            if status == "succeeded" and url:
                return url
            if status == "failed":
                raise AgnesError(f"云端 视频生成失败（video_id={video_id}）：{err}")
            await asyncio.sleep(self.poll_interval)

    @staticmethod
    async def download_media(url: str, timeout: float = 300.0) -> bytes:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.content


def parse_agnes_task_id(task_id: str) -> tuple[str, int] | None:
    """'agnes:<idx>:<video_id>' → (video_id, idx)；非 Agnes task 返回 None。"""
    if not task_id or not task_id.startswith("agnes:"):
        return None
    parts = task_id.split(":", 2)
    if len(parts) < 3:
        return None
    try:
        return parts[2], int(parts[1])
    except (ValueError, IndexError):
        return None


def resolve_agnes_sticky_key(
    task_id: str, client: AgnesClient | None = None
) -> str | None:
    """task_id → sticky key（内存表 → 编码 idx 取池内 key → 任意池内 key）。

    视频任务查询在同一账号池内 key 通用；重启丢失内存表后按 idx / 任意 key 兜底。
    client 可显式传入（冒烟/测试）；缺省走 get_agnes_client()。
    """
    if client is None:
        client = get_agnes_client()
    if client is None:
        return None
    parsed = parse_agnes_task_id(task_id)
    if parsed:
        video_id, idx = parsed
        key = client._video_keys.get(task_id) or client._video_keys.get(video_id)
        if key:
            return key
        if 0 <= idx < len(client.api_keys):
            return client.api_keys[idx]
    key = client._video_keys.get(task_id)
    if key:
        return key
    # 兜底：池内任意 key（轮询端点对同池 key 通用）
    return client.api_key or None




# ---------- 模块级单例 + 用户 key 作用域 ----------

import contextvars

# 当前任务/请求作用域内激活的「用户自加 Agnes key 池」。
# 由 services.agnes_keys.user_agnes_scope() 在任务执行/轮询前设置；
# get_agnes_client() 读取它，优先用用户 key，无则回退全局 AGNES_API_KEYS。
_user_agnes_scope: contextvars.ContextVar[tuple[str, ...] | None] = contextvars.ContextVar(
    "user_agnes_scope", default=None
)


def set_user_agnes_keys(keys: tuple[str, ...] | None) -> contextvars.Token:
    """设置当前作用域内的用户 Agnes key 池（供 get_agnes_client 优先使用）。"""
    return _user_agnes_scope.set(keys)


def reset_user_agnes_keys(token: contextvars.Token) -> None:
    _user_agnes_scope.reset(token)


def active_user_agnes_keys() -> tuple[str, ...] | None:
    """当前作用域内的用户 Agnes key 池（未注入为 None）。"""
    return _user_agnes_scope.get()


def _keys_from_settings() -> list[str]:
    from app.config import get_settings

    s = get_settings()
    keys = [k.strip() for k in (s.agnes_api_keys or "").split(",") if k.strip()]
    # 兼容：渠道 api_key 里也塞了 agnes key（单把）
    if not keys and (s.agnes_api_key or "").strip():
        keys = [s.agnes_api_key.strip()]
    return keys


# key 池签名 → client 的小缓存：同一池复用同一客户端，保证 sticky idx 稳定。
_client_cache: dict[tuple[str, ...], AgnesClient] = {}


def _get_cached_client(keys: list[str]) -> AgnesClient:
    from app.config import get_settings

    s = get_settings()
    sig = tuple(keys)
    cached = _client_cache.get(sig)
    if cached is None:
        cached = AgnesClient(
            keys,
            base_url=s.agnes_base_url or DEFAULT_BASE_URL,
            text_model=s.agnes_text_model or DEFAULT_TEXT_MODEL,
            image_model=s.agnes_image_model or DEFAULT_IMAGE_MODEL,
            video_model=s.agnes_video_model or DEFAULT_VIDEO_MODEL,
            poll_interval=s.agnes_video_poll_interval,
            poll_timeout=s.agnes_video_poll_timeout,
        )
        _client_cache[sig] = cached
    return cached


def get_agnes_client() -> AgnesClient | None:
    """优先返回当前作用域内的用户 Agnes key 池客户端；否则回退全局池。

    - 用户在「个人中心 / API」自加了 Agnes key 且当前任务处于其作用域内 →
      用该用户 key 提交/轮询 Agnes 视频；
    - 未注入用户 key 或用户未配置 → 回退全局 AGNES_API_KEYS（无则 None，走 TokenFree）。
    """
    user_keys = _user_agnes_scope.get()
    if user_keys:
        return _get_cached_client(list(user_keys))
    keys = _keys_from_settings()
    if not keys:
        return None
    return _get_cached_client(keys)


def reset_agnes_client() -> None:
    """清空客户端缓存（测试用；不影响用户作用域 ContextVar）。"""
    global _client_cache
    _client_cache = {}


def is_agnes_model(model: str | None) -> bool:
    return bool(model) and str(model).strip().lower().startswith("agnes-")
