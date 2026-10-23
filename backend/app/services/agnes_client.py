"""Agnes AI 异步客户端（httpx）：文本 / 图像 / 视频。

端点契约（Agnes 官方 API，2026-10；申请网址 https://new.aiwyq.bond，注册送 10 元免费额度）：
  Base URL     https://new.aiwyq.bond/v1
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
from urllib.parse import urlencode as _urlencode
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://new.aiwyq.bond/v1"
DEFAULT_TEXT_MODEL = "agnes-3.0-flash"
DEFAULT_IMAGE_MODEL = "agnes-image-2.5-flash"
DEFAULT_VIDEO_MODEL = "agnes-video-2.5-flash"

def _is_gateway_base(base_url: str) -> bool:
    """base_url 指向 new-api 网关时启用 OpenAI task 协议腿（网关丢弃 extra_body）。"""
    import re as _re
    host = _re.sub(r"^https?://", "", base_url or "").split("/")[0]
    return host.endswith(".aiwyq.bond") or "new-api" in (base_url or "")

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


# 网关 /videos 画幅档位（720P）：标签 → 像素；未知标签回落方形
_GATEWAY_VIDEO_SIZES = {"9:16": "720x1280", "16:9": "1280x720", "1:1": "720x720"}


def _gateway_video_size(ratio: str | None) -> str:
    key = str(ratio or "").strip()
    return _GATEWAY_VIDEO_SIZES.get(key, _GATEWAY_VIDEO_SIZES["1:1"])


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


_PROXY_DEAD_TTL = 60.0  # 死出口黑名单秒数（防立即重取同一坏 IP）


def _norm_proxy_url(s: str | None) -> str:
    """'host:port' / 'http://host:port' / 'http://user:pass@h:p' → 统一带 scheme。"""
    s = str(s or "").strip()
    if not s:
        return ""
    if "://" not in s:
        s = "http://" + s
    return s


def _mask_proxy(p: str) -> str:
    """日志掩码：104.12.3.4:8080 → 104.12.*.*；域名池 → ab.cd*。"""
    s = str(p or "").strip()
    if not s:
        return ""
    if "://" in s:
        s = s.split("://", 1)[1]
    host, _, _port = s.partition(":")
    parts = host.split(".")
    if len(parts) == 4 and all(x.isdigit() for x in parts[:3]):
        return ".".join([parts[0], parts[1], "*", "*"])
    return host[:6] + "*" if len(host) > 6 else (host or "*")


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
        proxy_pool_url: str = "",
        static_proxies: list[str] | None = None,
        proxy_type: str = "http",
        video_retry_rounds: int = 6,
    ) -> None:
        if not api_keys:
            raise AgnesError("Agnes 未配置任何 API key")
        self.api_keys = [k.strip() for k in api_keys if k and k.strip()]
        # 网关模式：base_url 指向 new-api 网关（如 new.aiwyq.bond）时，
        # 图片腿用顶层 b64_json（内联免下载 platform-outputs），视频腿走 OpenAI task 协议
        # （/videos 提交 + /videos/{id} 轮询 + /videos/{id}/content 下载）。
        # 原生 apihub 路径不动（仍走 native /agnesapi）。
        self.is_gateway = _is_gateway_base(base_url)
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.text_model = text_model or DEFAULT_TEXT_MODEL
        self.image_model = image_model or DEFAULT_IMAGE_MODEL
        self.video_model = video_model or DEFAULT_VIDEO_MODEL
        self.poll_interval = poll_interval
        self.poll_timeout = poll_timeout
        self.request_timeout = request_timeout
        # 视频提交遇 429/队列满时的换账号重试轮数（可配置，见 get_agnes_client）
        self.video_retry_rounds = max(1, int(video_retry_rounds))
        self._bad_keys: set[str] = set()
        self._key_rr = 0
        self._key_lock = asyncio.Lock()
        # (rpm_key, key) → last-timestamp
        self._throttle_last: dict[tuple[str, str], float] = {}
        self._throttle_lock = asyncio.Lock()
        # video_id → sticky key（提交→轮询→下载固定同一账号）
        self._video_keys: dict[str, str] = {}
        # ---- 代理池（每请求可换出口 IP，与 key 池轮换解耦，扩大可用面）----
        self.proxy_pool_url = str(proxy_pool_url or "").strip().rstrip("/")
        self.proxy_type = str(proxy_type or "http").lower() or "http"
        self._static_proxies: list[str] = [
            _norm_proxy_url(x) for x in (static_proxies or [])
        ]
        self._static_proxies = [x for x in self._static_proxies if x]
        self._proxy_rr = 0
        # 出口 → 黑名单截止时间（monotonic）
        self._proxy_blacklist: dict[str, float] = {}
        # video_id → sticky 出口（与 sticky key 对称绑定）
        self._video_proxies: dict[str, str] = {}

    # ---------- key 池 ----------

    @property
    def api_key(self) -> str:
        """默认（文本/图像）轮转选 key；sticky 场景请显式传 key。"""
        return self._pick_key_sync()

    def _gateway_key(self) -> str:
        """网关模式固定 key：提交/轮询/下载同源，防 401。"""
        return self.api_keys[0] if self.api_keys else ""

    def _pick_key_sync(self, fast_lane: bool = False) -> str:
        """轮转选 key；fast_lane=True（视频快车道）优先近 10 分钟成功过的 key。"""
        try:
            from app.services.agnes_key_pool import acquire

            got = acquire(exclude=self._bad_keys, fast_lane=fast_lane)
            key = str(got.get("key") or "").strip()
            if key:
                if key not in self.api_keys:
                    self.api_keys.append(key)
                return key
        except LookupError:
            pass
        except Exception as exc:  # noqa: BLE001
            logger.debug("[Agnes] 本地 key 池取用失败：%s", exc)
        n = len(self.api_keys)
        for i in range(n):
            k = self.api_keys[(self._key_rr + i) % n]
            if k not in self._bad_keys:
                self._key_rr = (self._key_rr + i + 1) % n
                return k
        return self.api_keys[0]

    def _mark_ok(self, key: str) -> None:
        if not key:
            return
        try:
            from app.services.agnes_key_pool import mark_result

            mark_result(key, ok=True)
        except KeyError:
            pass
        except Exception as exc:  # noqa: BLE001
            logger.debug("[Agnes] 本地 key 池记成功失败：%s", exc)

    def _mark_bad(self, key: str, reason: str) -> None:
        if key not in self._bad_keys:
            self._bad_keys.add(key)
            logger.warning("[Agnes] key %s 失效（%s），切换到下一账号", _short_key(key), reason)
        try:
            from app.services.agnes_key_pool import mark_result, set_status

            text = reason or ""
            if "401" in text or "403" in text:
                try:
                    set_status(key, "exhausted")
                except KeyError:
                    pass
            else:
                mark_result(key, ok=False, error=text)
        except KeyError:
            pass
        except Exception as exc:  # noqa: BLE001
            logger.debug("[Agnes] 本地 key 池记失败失败：%s", exc)

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

    # ---------- 代理池 ----------

    async def _pool_random_get(self) -> str:
        """GET {pool}/get/?type=… 随机取一个出口；池挂/空 → ''（快速降级直连）。"""
        if not self.proxy_pool_url:
            return ""
        url = self.proxy_pool_url + "/get/?" + _urlencode(
            {"type": self.proxy_type} if self.proxy_type else {}
        )
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(url)
            data = resp.json()
            host = str(data.get("proxy") or "").strip()
            return _norm_proxy_url(host)
        except Exception as e:  # noqa: BLE001 — 池不可用不得影响主链路
            logger.warning("[Agnes] 代理池 /get 失败（%s），本轮回退直连", e)
            return ""

    async def _pool_delete(self, proxy_url: str) -> None:
        """坏代理剔回池（best-effort；池挂则仅本地黑名单）。"""
        if not self.proxy_pool_url:
            return
        host = proxy_url.split("://", 1)[1] if "://" in proxy_url else proxy_url
        url = self.proxy_pool_url + "/delete/?" + _urlencode({"proxy": host})
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.get(url)
            logger.info("[Agnes] 失效代理 %s 已剔回池", _mask_proxy(proxy_url))
        except Exception:  # noqa: BLE001
            pass

    async def _pick_proxy(self, key: str = "") -> str:
        """本请求出口：池随机 > 静态轮转 > 直连（''）。

        - 黑名单内（_PROXY_DEAD_TTL）的出口不取
        - 池随机时避开其他视频任务已绑定的 sticky 出口（保持出口隔离）
        - 池取空 / 全死 → 静态池 → 直连（可用性优先于隔离性）
        """
        now = time.monotonic()

        def _alive(p: str) -> bool:
            return self._proxy_blacklist.get(p, 0.0) <= now

        if self.proxy_pool_url:
            taken = {x for x in self._video_proxies.values() if x}
            cand = ""
            for _ in range(5):
                cand = await self._pool_random_get()
                if not cand:
                    break  # 池空/挂，落静态
                if _alive(cand) and cand not in taken:
                    return cand
            if cand and _alive(cand):
                return cand  # 池太小撞满，允许碰撞（优于直连）
        if self._static_proxies:
            n = len(self._static_proxies)
            for i in range(n):
                idx = (self._proxy_rr + i) % n
                cand = self._static_proxies[idx]
                if _alive(cand):
                    self._proxy_rr = (idx + 1) % n
                    return cand
        return ""

    async def _report_dead_proxy(self, proxy_url: str, reason: str = "") -> None:
        """出口失效：本地黑名单 + 池 /delete/（best-effort）。"""
        p = _norm_proxy_url(proxy_url)
        if not p:
            return
        self._proxy_blacklist[p] = time.monotonic() + _PROXY_DEAD_TTL
        logger.warning(
            "[Agnes] 出口 %s 失效（%s），%.0fs 黑名单%s",
            _mask_proxy(p), (reason or "连接失败")[:80], _PROXY_DEAD_TTL,
            "；剔回池" if self.proxy_pool_url else "",
        )
        await self._pool_delete(p)

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
        proxy: str | None = None,
    ) -> dict[str, Any]:
        """单次 POST；429 非 sticky 时自动换 key（+换出口），401/403 标坏并切换。

        proxy: 本次出口（''=直连）；连接失败剔坏换出口重试，账号轮换同时换出口。
        """
        body = json.dumps(payload).encode("utf-8")
        active = key or self._pick_key_sync()
        if proxy is None:
            proxy = ""
        key_idx = 0
        total = len(self.api_keys) if not sticky else 1
        while True:
            last_err: Exception | None = None
            for i in range(retries + 1):
                try:
                    kwargs: dict[str, Any] = {"timeout": timeout or self.request_timeout}
                    if proxy:
                        kwargs["proxy"] = proxy
                    async with httpx.AsyncClient(**kwargs) as client:
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
                            f"云端 HTTP {resp.status_code}（账号 {_short_key(active)} 出口 {_mask_proxy(proxy) or '直连'}）："
                            f"{json.dumps(data, ensure_ascii=False)[:400]}"
                        )
                    self._mark_ok(active)
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
                            if not self.is_gateway:
                                proxy = await self._pick_proxy(active)  # 新账号 → 新出口
                            logger.info(
                                "[Agnes] 429 换账号 → %s（出口 %s）",
                                _short_key(active), _mask_proxy(proxy) or "直连",
                            )
                            last_err = None  # 换 key 后外层重开一轮，勿把 429 当作重试耗尽
                            break  # 换 key 重开一轮
                        raise
                    if "HTTP 401" in msg or "HTTP 403" in msg:
                        self._mark_bad(active, msg[:80])
                        if not sticky and key_idx + 1 < total and len(self._bad_keys) < len(self.api_keys):
                            key_idx += 1
                            active = self._pick_key_sync()
                            if not self.is_gateway:
                                proxy = await self._pick_proxy(active)
                            last_err = None
                            break
                        raise
                    if i < retries:
                        await asyncio.sleep(1.5 * (i + 1))
                        continue
                    raise
                except httpx.HTTPError as e:
                    last_err = e
                    if proxy:
                        await self._report_dead_proxy(proxy, str(e)[:80])
                    if i < retries:
                        if not self.is_gateway:
                            proxy = await self._pick_proxy(active)  # 换出口重试
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
        if self.is_gateway:
            key = self._gateway_key()
            proxy = ""
        else:
            key = self._pick_key_sync()
            proxy = await self._pick_proxy(key)
        await self._throttle("text", key, "文本")
        resp = await self._post_json(
            self.base_url + "/chat/completions",
            payload,
            key=key,
            timeout=240.0,
            proxy=proxy,
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
        if self.is_gateway:
            # 网关 new-api：extra_body 会被丢弃，response_format/image 必须放顶层。
            # 顶层 b64_json → 网关直接回内联字节；参考图支持列表，最多 5 张
            # （实测网关 /images/generations 顶层 image 接受 data-URI 列表）。
            payload: dict[str, Any] = {
                "model": model or self.image_model,
                "prompt": str(prompt),
                "size": eff_size,
                "ratio": eff_ratio,
                "response_format": "b64_json",
            }
            if refs:
                payload["image"] = refs[:5]
            key = self._gateway_key()
            proxy = ""
        else:
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
            proxy = ""
        rpm = _image_rpm_key(eff_size)
        await self._throttle(rpm, key, f"生图 {str(eff_size).upper()} 档")
        if not self.is_gateway:
            proxy = await self._pick_proxy(key)
        resp = await self._post_json(
            self.base_url + "/images/generations",
            payload,
            key=key,
            timeout=360.0,
            proxy=proxy,
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
        async def _to_uri(u: str | None, hint_i: int) -> str:
            hint = local_hints[hint_i] if local_hints and hint_i < len(local_hints) else None
            return await self._data_uri_for(u, hint) if u else ""

        if self.is_gateway:
            # OpenAI 网关 task 协议：/videos 收 {model, prompt, size}；参考图走顶层 image。
            # 网关 agnes 插件 v1.0.1 起支持多参考图（refImages 去重≤5 完整透传上游），
            # 首帧优先、否则取前 5 张参考图（_to_uri 会本地→data URI，hint 按下标对齐）。
            payload: dict[str, Any] = {
                "model": model,
                "prompt": str(prompt),
                "duration": sec,
                # 画幅：size 按标签映射 720P 像素（9:16→720x1280 / 16:9→1280x720 / 1:1→720x720），
                # 不再写死方形 512x512；同时透传 aspect_ratio 标签供上游可选识别。
                "size": _gateway_video_size(ratio),
                "aspect_ratio": ratio or "1:1",
            }
            if first_frame:
                ref0 = await _to_uri(first_frame, 0)
                if ref0:
                    payload["image"] = [ref0]
            elif ref_images:
                imgs = []
                for i in range(min(len(ref_images), 5)):
                    d = await _to_uri(ref_images[i], i)
                    if d:
                        imgs.append(d)
                if imgs:
                    payload["image"] = imgs
        else:
            payload = {
                "model": model,
                "prompt": str(prompt),
                "mode": mode,
                "seconds": str(sec),
                "size": "720P",
                "aspect_ratio": ratio or "16:9",
                "n": 1,
            }
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

        if self.is_gateway:
            sticky = self._gateway_key()
            proxy = ""
            await self._throttle("video", sticky, "视频任务")
        else:
            sticky = self._pick_key_sync(fast_lane=True)
            await self._throttle("video", sticky, "视频任务")
            proxy = await self._pick_proxy(sticky)
        # 容量感知排队（P1）：雷达状态驱动内部重试轮数——
        #   OPEN（饱和）坍缩为 1 轮，立即重排队（往返 ~15s）
        #   CLOSED/PROBING（有容量）保留多轮换 key（命中率高）
        from app.services.tasks.capacity_radar import get_capacity_radar
        radar = get_capacity_radar()
        max_backoff_rounds = radar.video_retry_rounds()
        # 令牌桶：提交前取一个速率令牌；等待 > 5s 时记录日志（不 sleep，由雷达退避控制节奏）
        slot_wait = radar.acquire_submit_slot()
        if slot_wait > 5.0:
            logger.info("[Agnes] 令牌桶限速等待 %.0fs（rate 门控）", slot_wait)
        resp: dict[str, Any] | None = None
        for attempt in range(max_backoff_rounds):
            try:
                resp = await self._post_json(
                    self.base_url + "/videos",
                    payload,
                    key=sticky,
                    sticky=True,
                    timeout=120.0,
                    proxy=proxy,
                )
                break
            except AgnesError as exc:
                msg = str(exc)
                transient = (
                    "HTTP 503" in msg
                    or "video_queue_full" in msg
                    or "HTTP 429" in msg
                    or "HTTP 5" in msg
                    or "请求失败" in msg
                )
                if not transient or attempt == max_backoff_rounds - 1:
                    raise
                backoff = min(20.0 * (attempt + 1), 120.0)
                # 上游拥塞/配额限流：轮换账号+出口再试。不同 key 视频队列独立，
                # 换 key 更易命中队列未满的账号（实测 28 把 key 约 6 把可 200），
                # 命中率远高于锁死单 key 反复 503。
                if not self.is_gateway:
                    sticky = self._pick_key_sync()
                    proxy = await self._pick_proxy(sticky)
                await self._throttle("video", sticky, "视频任务")
                logger.warning(
                    "[Agnes] 视频提交遇 %s，换账号 %s 退避 %.0fs 后重试（第 %d/%d 轮）",
                    msg[:120], _short_key(sticky), backoff, attempt + 1, max_backoff_rounds,
                )
                await asyncio.sleep(backoff)
        assert resp is not None
        video_id = self._extract_video_id(resp)
        # 自描述 task_id：编码 sticky key 下标，重启后也能找回提交账号
        try:
            key_index = self.api_keys.index(sticky)
        except ValueError:
            key_index = 0
        task_id = f"agnes:{key_index}:{video_id}"
        self._video_keys[task_id] = sticky
        self._video_keys[video_id] = sticky
        # sticky 出口：轮询/下载固定同一出口（与 sticky key 对称绑定）
        self._video_proxies[task_id] = proxy
        self._video_proxies[video_id] = proxy
        logger.info(
            "[Agnes] 视频提交 mode=%s %ss ratio=%s 参考=%d 账号=%s 出口=%s task_id=%s",
            mode, sec, payload.get("aspect_ratio") or payload.get("size") or "-",
            len(ref_images or []),
            _short_key(sticky), _mask_proxy(proxy) or "直连", task_id,
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
        self, video_id: str, model: str, key: str, proxy: str | None = None
    ) -> tuple[str, str | None, str | None]:
        """单次轮询 → (status, url, error)。status: running|succeeded|failed。"""
        proxy = proxy or self._video_proxies.get(video_id, "")
        if self.is_gateway:
            url = f"{self.base_url}/videos/{video_id}"
        else:
            query = _urlencode({"video_id": video_id, "model_name": model or self.video_model})
            url = self._query_url() + "?" + query
        try:
            kwargs: dict[str, Any] = {"timeout": 60.0, "follow_redirects": True}
            if proxy and not self.is_gateway:
                kwargs["proxy"] = proxy
            async with httpx.AsyncClient(**kwargs) as client:
                resp = await client.get(
                    url, headers={"Authorization": f"Bearer {key}"}
                )
            if resp.status_code == 429:
                return "running", None, "rate_limited"
            if resp.status_code >= 400:
                return "failed", None, f"HTTP {resp.status_code}: {resp.text[:200]}"
            data = resp.json()
        except httpx.HTTPError as e:
            if proxy:
                await self._report_dead_proxy(proxy, "poll network")
            return "running", None, f"poll network: {e}"
        if not isinstance(data, dict):
            return "running", None, "poll response not json"
        if self.is_gateway:
            # 网关 OpenAI task 协议：status + /videos/{id}/content 下载（Bearer 同源 key）
            status = str(data.get("status") or "").lower()
            if status in ("completed", "succeeded", "success", "done", "finished"):
                content_url = f"{self.base_url}/videos/{video_id}/content"
                return "succeeded", content_url, None
            if status in ("failed", "fail", "error", "cancelled", "canceled"):
                msg = data.get("error") or data.get("message") or status or "failed"
                return "failed", None, str(msg)[:300]
            return "running", None, None
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
            if err and "poll network" in str(err):
                # 出口失效：剔坏后换出口继续等（任务归属 key 不变）
                self._video_proxies.pop(video_id, None)
                new_proxy = await self._pick_proxy(key)
                self._video_proxies[video_id] = new_proxy
                logger.info(
                    "[Agnes] 视频 %s 出口失效，换出口 %s 继续",
                    video_id, _mask_proxy(new_proxy) or "直连",
                )
            await asyncio.sleep(self.poll_interval)

    async def download_media(
        self, url: str, timeout: float = 300.0, proxy: str = "",
        key: str = "",
    ) -> bytes:
        """下载媒体 URL。网关 /videos/{id}/content 需 Bearer 同源 key。"""
        kwargs: dict[str, Any] = {"timeout": timeout, "follow_redirects": True}
        if proxy and not self.is_gateway:
            kwargs["proxy"] = proxy
        headers = {}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        async with httpx.AsyncClient(**kwargs) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code >= 400:
                raise AgnesError(
                    f"云端 媒体下载失败 HTTP {resp.status_code}: {resp.text[:200]}"
                )
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




# ---------- 模块级单例（从 settings 构建） ----------

_agnes_client: AgnesClient | None = None
_agnes_client_keys: tuple[str, ...] = ()


def _keys_from_settings() -> list[str]:
    from app.config import get_settings

    s = get_settings()
    keys = [k.strip() for k in (s.agnes_api_keys or "").split(",") if k.strip()]
    # 兼容：渠道 api_key 里也塞了 agnes key（单把）
    if not keys and (s.agnes_api_key or "").strip():
        keys = [s.agnes_api_key.strip()]
    pool_keys: list[str] = []
    try:
        from app.services.agnes_key_pool import active_secrets

        pool_keys = active_secrets()
    except Exception:  # noqa: BLE001
        pool_keys = []
    seen: set[str] = set()
    merged: list[str] = []
    for key in pool_keys + keys:
        if key and key not in seen:
            seen.add(key)
            merged.append(key)
    return merged


def get_agnes_client() -> AgnesClient | None:
    """配置了 AGNES_API_KEYS / 本地 key 池时返回客户端；否则 None（走 TokenFree）。"""
    global _agnes_client, _agnes_client_keys
    from app.config import get_settings

    keys = _keys_from_settings()
    if not keys:
        return None
    s = get_settings()
    sig = tuple(keys)
    if _agnes_client is None or sig != _agnes_client_keys:
        _agnes_client = AgnesClient(
            keys,
            base_url=s.agnes_base_url or DEFAULT_BASE_URL,
            text_model=s.agnes_text_model or DEFAULT_TEXT_MODEL,
            image_model=s.agnes_image_model or DEFAULT_IMAGE_MODEL,
            video_model=s.agnes_video_model or DEFAULT_VIDEO_MODEL,
            poll_interval=s.agnes_video_poll_interval,
            poll_timeout=s.agnes_video_poll_timeout,
            proxy_pool_url=s.agnes_proxy_pool_url,
            # 静态代理入口（AGNES_HTTP_PROXY，可逗号分隔多个）；动态池优先
            static_proxies=[
                x.strip() for x in (s.agnes_http_proxy or "").split(",") if x.strip()
            ],
            proxy_type="http",
            video_retry_rounds=getattr(s, "agnes_video_retry_rounds", 6),
        )
        _agnes_client_keys = sig
    return _agnes_client


def reset_agnes_client() -> None:
    global _agnes_client, _agnes_client_keys
    _agnes_client = None
    _agnes_client_keys = ()


def is_agnes_model(model: str | None) -> bool:
    return bool(model) and str(model).strip().lower().startswith("agnes-")
