"""
WebDriver HTTP 基类 - 对应 packages/webdriver/src/clients/WebDriverClient.ts

基于 httpx 的异步 HTTP 客户端, 提供 W3C WebDriver 的基础操作
(session、screenshot、window size、device info). iOS WDA / Android 的 appium /
Selenium 都继承自这个协议.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

import httpx

from ..shared.logger import logger


class WebDriverError(RuntimeError):
    """WebDriver HTTP 请求失败的通用异常."""


class WebDriverClient:
    """
    WebDriver HTTP 协议基类. 子类 (iOS WDA 等) 在此之上添加平台专属端点.

    Args:
        host: WebDriver 服务端 host (默认 ``localhost``)
        port: WebDriver 服务端 port (默认 ``8100`` 供 WDA 用)
        base_url: 直接指定完整 base URL, 覆盖 host+port
        timeout: HTTP 请求超时 (秒)
        transport: httpx 自定义 transport (测试时用 MockTransport 注入)
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 8100,
        base_url: Optional[str] = None,
        timeout: float = 30.0,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        self.host = host
        self.port = port
        self.base_url = base_url or f"http://{host}:{port}"
        self.timeout = timeout
        self._transport = transport
        self.session_id: Optional[str] = None
        self._client: Optional[httpx.AsyncClient] = None
        self._client_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # httpx 客户端
    # ------------------------------------------------------------------

    async def _get_client(self) -> httpx.AsyncClient:
        """懒加载 httpx.AsyncClient. 线程/协程安全."""
        if self._client is not None:
            return self._client
        async with self._client_lock:
            if self._client is None:
                self._client = httpx.AsyncClient(
                    base_url=self.base_url,
                    timeout=self.timeout,
                    transport=self._transport,
                )
        return self._client

    async def aclose(self) -> None:
        """关闭底层 HTTP 客户端."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # 原始 HTTP
    # ------------------------------------------------------------------

    async def make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[dict[str, Any]] = None,
    ) -> Any:
        """
        执行 WebDriver HTTP 请求.

        - 4xx/5xx 响应中, 若 body 含 ``value.error`` 会抛 WebDriverError.
        - 返回整个解析后的 JSON (调用者自行取 ``value`` 字段).
        - GET /screenshot 之类返回二进制字符串的, 直接返回 body 文本.
        """
        client = await self._get_client()
        path = endpoint if endpoint.startswith("/") else f"/{endpoint}"
        logger.debug(f"WDA {method} {path} {data}")
        if data is None:
            response = await client.request(method, path)
        else:
            response = await client.request(method, path, json=data)
        return self._parse_response(response, method, path)

    @staticmethod
    def _parse_response(
        response: httpx.Response, method: str, path: str
    ) -> Any:
        content_type = response.headers.get("content-type", "")
        if response.status_code >= 400:
            body: Any = None
            try:
                body = response.json()
            except Exception:
                body = response.text
            if isinstance(body, dict):
                err = body.get("value", {})
                if isinstance(err, dict) and err.get("error"):
                    raise WebDriverError(
                        f"WDA {method} {path} failed: "
                        f"{err.get('error')} - {err.get('message', '')}"
                    )
            raise WebDriverError(
                f"WDA {method} {path} failed with {response.status_code}: {body}"
            )

        if "application/json" in content_type or response.text.startswith(
            ("{", "[")
        ):
            try:
                return response.json()
            except Exception:
                return response.text
        return response.text

    # ------------------------------------------------------------------
    # 会话管理
    # ------------------------------------------------------------------

    async def create_session(
        self, capabilities: Optional[dict[str, Any]] = None
    ) -> dict[str, Any]:
        """
        创建 WebDriver 会话. 对齐 JS `createSession`.

        Returns:
            ``{"sessionId": ..., "capabilities": {...}}``
        """
        payload = {
            "capabilities": {
                "alwaysMatch": {**(capabilities or {})},
            }
        }
        response = await self.make_request("POST", "/session", payload)
        # 兼容新老响应结构
        session_id = response.get("sessionId") or response.get("value", {}).get(
            "sessionId"
        )
        if not session_id:
            raise WebDriverError(
                f"Failed to get session ID from response: {response}"
            )
        self.session_id = session_id
        caps = response.get("capabilities") or response.get("value", {}).get(
            "capabilities", {}
        )
        return {"sessionId": session_id, "capabilities": caps}

    async def delete_session(self) -> None:
        """对齐 JS `deleteSession`. Best-effort."""
        if not self.session_id:
            return
        try:
            await self.make_request("DELETE", f"/session/{self.session_id}")
        except Exception as exc:
            logger.debug(f"WDA delete_session failed (ignored): {exc}")
        finally:
            self.session_id = None

    def ensure_session(self) -> str:
        """确保 session 已建立, 否则抛出."""
        if not self.session_id:
            raise WebDriverError(
                "No active WebDriver session. Call create_session() first."
            )
        return self.session_id

    # ------------------------------------------------------------------
    # 标准 WebDriver 操作
    # ------------------------------------------------------------------

    async def take_screenshot(self) -> str:
        """
        截屏, 返回 base64 PNG 字符串.

        WDA `/session/{id}/screenshot` 返回 ``{"value": "<base64>"}``.
        """
        self.ensure_session()
        response = await self.make_request(
            "GET", f"/session/{self.session_id}/screenshot"
        )
        if isinstance(response, dict):
            return response.get("value") or ""
        return str(response)

    async def get_window_size(self) -> dict[str, int]:
        """
        获取窗口尺寸. 对齐 JS `getWindowSize`.

        优先 ``/window/rect`` (新协议), 回退 ``/window/size``.
        """
        self.ensure_session()
        try:
            response = await self.make_request(
                "GET", f"/session/{self.session_id}/window/rect"
            )
            rect = response.get("value") if isinstance(response, dict) else response
            if isinstance(rect, dict) and "width" in rect:
                return {
                    "width": int(rect["width"]),
                    "height": int(rect["height"]),
                }
        except Exception as exc:
            logger.debug(f"/window/rect failed: {exc}, fallback to /window/size")

        response = await self.make_request(
            "GET", f"/session/{self.session_id}/window/size"
        )
        size = response.get("value") if isinstance(response, dict) else response
        return {"width": int(size["width"]), "height": int(size["height"])}

    async def get_device_info(self) -> Optional[dict[str, str]]:
        """
        获取设备信息. 对齐 JS `getDeviceInfo`.

        通过 ``/status`` 端点. 失败返回 None.
        """
        try:
            response = await self.make_request("GET", "/status")
            value = (
                response.get("value")
                if isinstance(response, dict) and "value" in response
                else response
            )
            device = (
                value.get("device") if isinstance(value, dict) else None
            ) or (
                response.get("device") if isinstance(response, dict) else None
            )
            if not isinstance(device, dict):
                return None
            return {
                "udid": str(device.get("udid") or device.get("identifier") or ""),
                "name": str(device.get("name") or ""),
                "model": str(
                    device.get("model") or device.get("productName") or ""
                ),
            }
        except Exception as exc:
            logger.debug(f"get_device_info failed: {exc}")
            return None


__all__ = ["WebDriverClient", "WebDriverError"]
