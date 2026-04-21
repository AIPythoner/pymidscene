"""
IOSWebDriverClient - 对应 packages/ios/src/ios-webdriver-client.ts

WebDriverAgent (WDA) iOS 专属 HTTP 客户端. 封装:

- tap / double_tap / triple_tap / long_press / swipe
- launch_app / activate_app / terminate_app / open_url
- press_home_button / app_switcher
- type_text / press_key / dismiss_keyboard
- clear_active_element (基于 active element)
- get_screen_scale (优先 `/wda/screen`, 退回 截图/窗口比例计算)

WDA 不同版本端点略有差异, 客户端内部有新旧端点 fallback.
"""

from __future__ import annotations

import asyncio
import base64
import io
from typing import Any, Optional

from ..shared.logger import logger
from ..webdriver.client import WebDriverClient, WebDriverError


class IOSWebDriverClient(WebDriverClient):
    """iOS WDA 客户端."""

    # ------------------------------------------------------------------
    # 会话创建 - 注入 iOS 默认 capabilities
    # ------------------------------------------------------------------

    async def create_session(
        self, capabilities: Optional[dict[str, Any]] = None
    ) -> dict[str, Any]:
        default_caps = {
            "platformName": "iOS",
            "automationName": "XCUITest",
            "shouldUseSingletonTestManager": False,
            "shouldUseTestManagerForVisibilityDetection": False,
        }
        if capabilities:
            default_caps.update(capabilities)
        session = await super().create_session(default_caps)
        # 可选的后置配置: 调整 snapshot 深度等
        try:
            await self.make_request(
                "POST",
                f"/session/{self.session_id}/appium/settings",
                {
                    "settings": {
                        "snapshotMaxDepth": 50,
                        "elementResponseAttributes": "type,label,name,value,rect,enabled,visible",
                    }
                },
            )
        except Exception as exc:  # 非致命, 旧 WDA 可能不支持
            logger.debug(f"iOS session post-setup skipped: {exc}")
        return session

    # ------------------------------------------------------------------
    # app / URL
    # ------------------------------------------------------------------

    async def launch_app(self, bundle_id: str) -> None:
        self.ensure_session()
        await self.make_request(
            "POST",
            f"/session/{self.session_id}/wda/apps/launch",
            {"bundleId": bundle_id},
        )

    async def activate_app(self, bundle_id: str) -> None:
        self.ensure_session()
        await self.make_request(
            "POST",
            f"/session/{self.session_id}/wda/apps/activate",
            {"bundleId": bundle_id},
        )

    async def terminate_app(self, bundle_id: str) -> None:
        self.ensure_session()
        await self.make_request(
            "POST",
            f"/session/{self.session_id}/wda/apps/terminate",
            {"bundleId": bundle_id},
        )

    async def open_url(self, url: str) -> None:
        """
        打开 URL. 对齐 JS `openUrl`.

        优先走 ``POST /session/{id}/url``; 失败则启动 Safari 后再试.
        """
        self.ensure_session()
        try:
            await self.make_request(
                "POST", f"/session/{self.session_id}/url", {"url": url}
            )
        except Exception as exc:
            logger.debug(f"Direct URL open failed, fallback via Safari: {exc}")
            await self.launch_app("com.apple.mobilesafari")
            await asyncio.sleep(2)
            await self.make_request(
                "POST", f"/session/{self.session_id}/url", {"url": url}
            )

    # ------------------------------------------------------------------
    # 物理按键
    # ------------------------------------------------------------------

    async def press_home_button(self) -> None:
        self.ensure_session()
        await self.make_request(
            "POST",
            f"/session/{self.session_id}/wda/pressButton",
            {"name": "home"},
        )

    async def app_switcher(self) -> None:
        """慢速上滑触发多任务. 对齐 JS `appSwitcher`."""
        self.ensure_session()
        size = await self.get_window_size()
        cx = size["width"] // 2
        start_y = size["height"] - 5
        end_y = size["height"] // 2
        await self.swipe(cx, start_y, cx, end_y, duration_ms=1500)
        await asyncio.sleep(0.8)

    # ------------------------------------------------------------------
    # 触控操作
    # ------------------------------------------------------------------

    async def tap(self, x: int, y: int) -> None:
        self.ensure_session()
        try:
            await self.make_request(
                "POST",
                f"/session/{self.session_id}/wda/tap",
                {"x": x, "y": y},
            )
        except Exception as exc:
            logger.debug(f"New /wda/tap failed, trying /wda/tap/0: {exc}")
            await self.make_request(
                "POST",
                f"/session/{self.session_id}/wda/tap/0",
                {"x": x, "y": y},
            )

    async def double_tap(self, x: int, y: int) -> None:
        self.ensure_session()
        await self.make_request(
            "POST",
            f"/session/{self.session_id}/wda/doubleTap",
            {"x": x, "y": y},
        )

    async def triple_tap(self, x: int, y: int) -> None:
        self.ensure_session()
        await self.make_request(
            "POST",
            f"/session/{self.session_id}/wda/tapWithNumberOfTaps",
            {"x": x, "y": y, "numberOfTaps": 3, "numberOfTouches": 1},
        )

    async def long_press(self, x: int, y: int, duration_ms: int = 1000) -> None:
        self.ensure_session()
        await self.make_request(
            "POST",
            f"/session/{self.session_id}/wda/touchAndHold",
            {"x": x, "y": y, "duration": duration_ms / 1000},
        )

    async def swipe(
        self,
        from_x: int,
        from_y: int,
        to_x: int,
        to_y: int,
        duration_ms: int = 500,
    ) -> None:
        """用 W3C Actions API 实现, 比 WDA 老版 /wda/dragfromtoforduration 稳定."""
        self.ensure_session()
        actions = {
            "actions": [
                {
                    "type": "pointer",
                    "id": "finger1",
                    "parameters": {"pointerType": "touch"},
                    "actions": [
                        {
                            "type": "pointerMove",
                            "duration": 0,
                            "x": from_x,
                            "y": from_y,
                        },
                        {"type": "pointerDown", "button": 0},
                        {"type": "pause", "duration": 100},
                        {
                            "type": "pointerMove",
                            "duration": duration_ms,
                            "x": to_x,
                            "y": to_y,
                        },
                        {"type": "pointerUp", "button": 0},
                    ],
                }
            ]
        }
        await self.make_request(
            "POST", f"/session/{self.session_id}/actions", actions
        )

    # ------------------------------------------------------------------
    # 键盘
    # ------------------------------------------------------------------

    async def type_text(self, text: str) -> None:
        """通过 WDA `/wda/keys` 一次性输入文本. 每个字符单独放入 value 数组."""
        if not text:
            return
        self.ensure_session()
        clean = text.strip() if text.strip() else text
        await self.make_request(
            "POST",
            f"/session/{self.session_id}/wda/keys",
            {"value": list(clean)},
        )

    async def press_key(self, key: str) -> None:
        """
        单键映射. 对齐 JS `pressKey`.
        """
        self.ensure_session()
        normalized = (key or "").strip()
        if not normalized:
            return

        if normalized in ("Enter", "Return", "return"):
            await self._send_keys(["\n"])
            await asyncio.sleep(0.1)
            return
        if normalized in ("Backspace", "Delete"):
            try:
                await self._send_keys(["\b"])
                return
            except Exception as exc:
                logger.debug(f"Backspace failed: {exc}")
        if normalized == "Space":
            try:
                await self._send_keys([" "])
                return
            except Exception as exc:
                logger.debug(f"Space failed: {exc}")

        # 额外的键映射 (与 JS 版 iosKeyMap 对齐). Python 版做大小写/空格不敏感匹配,
        # JS 版本身对 Arrow* 类驼峰键有 bug (normalize 后变 "Arrowup" 匹配不到).
        ios_key_map = {
            "Tab": "\t",
            "ArrowUp": "\uE013",
            "ArrowDown": "\uE015",
            "ArrowLeft": "\uE012",
            "ArrowRight": "\uE014",
            "Home": "\uE011",
            "End": "\uE010",
        }
        lower_map = {k.lower(): v for k, v in ios_key_map.items()}
        if normalized.lower() in lower_map:
            try:
                await self._send_keys([lower_map[normalized.lower()]])
                return
            except Exception as exc:
                logger.debug(f"WebDriver key failed for {normalized}: {exc}")

        if len(normalized) == 1:
            try:
                await self._send_keys([normalized])
                return
            except Exception as exc:
                logger.debug(f"Single char {normalized} failed: {exc}")

        raise WebDriverError(f'Key "{normalized}" is not supported on iOS')

    @staticmethod
    def _normalize_key_name(key: str) -> str:
        return key[0].upper() + key[1:].lower()

    async def _send_keys(self, values: list[str]) -> None:
        await self.make_request(
            "POST",
            f"/session/{self.session_id}/wda/keys",
            {"value": values},
        )

    async def dismiss_keyboard(
        self, key_names: Optional[list[str]] = None
    ) -> bool:
        """对齐 JS `dismissKeyboard`. 失败返回 False."""
        self.ensure_session()
        try:
            await self.make_request(
                "POST",
                f"/session/{self.session_id}/wda/keyboard/dismiss",
                {"keyNames": key_names or ["done"]},
            )
            return True
        except Exception as exc:
            logger.debug(f"dismiss_keyboard failed: {exc}")
            return False

    # ------------------------------------------------------------------
    # 元素 clear
    # ------------------------------------------------------------------

    async def get_active_element(self) -> Optional[str]:
        """
        获取当前焦点元素的 WebDriver element id. 无则返回 None.
        """
        self.ensure_session()
        try:
            response = await self.make_request(
                "GET", f"/session/{self.session_id}/element/active"
            )
        except Exception as exc:
            logger.debug(f"get_active_element failed: {exc}")
            return None
        candidates = [response]
        if isinstance(response, dict):
            candidates.append(response.get("value"))
        w3c_key = "element-6066-11e4-a52e-4f735466cecf"
        for c in candidates:
            if isinstance(c, dict):
                for k in ("ELEMENT", w3c_key):
                    if c.get(k):
                        return str(c[k])
        return None

    async def clear_element(self, element_id: str) -> None:
        self.ensure_session()
        await self.make_request(
            "POST",
            f"/session/{self.session_id}/element/{element_id}/clear",
        )

    async def clear_active_element(self) -> bool:
        element_id = await self.get_active_element()
        if not element_id:
            return False
        try:
            await self.clear_element(element_id)
            return True
        except Exception as exc:
            logger.debug(f"clear_element failed: {exc}")
            return False

    # ------------------------------------------------------------------
    # 屏幕信息
    # ------------------------------------------------------------------

    async def get_screen_scale(self) -> Optional[float]:
        """
        获取屏幕缩放 (dpr). 对齐 JS `getScreenScale`.

        优先 ``/wda/screen``; 失败则从 screenshot 尺寸 / window size 计算.
        """
        self.ensure_session()
        try:
            response = await self.make_request(
                "GET", f"/session/{self.session_id}/wda/screen"
            )
            value = response.get("value") if isinstance(response, dict) else None
            if isinstance(value, dict) and "scale" in value:
                return float(value["scale"])
        except Exception as exc:
            logger.debug(f"/wda/screen failed: {exc}")

        try:
            b64, size = await asyncio.gather(
                self.take_screenshot(),
                self.get_window_size(),
            )
            try:
                from PIL import Image
            except ImportError:
                return None
            img = Image.open(io.BytesIO(base64.b64decode(b64)))
            screenshot_max = max(img.size)
            window_max = max(size["width"], size["height"])
            if window_max <= 0:
                return None
            return round(screenshot_max / window_max)
        except Exception as exc:
            logger.debug(f"fallback screen scale calc failed: {exc}")
        return None

    async def execute_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[dict[str, Any]] = None,
    ) -> Any:
        """对齐 JS `executeRequest` - 直接透传到 WDA HTTP."""
        self.ensure_session()
        return await self.make_request(method, endpoint, data)


__all__ = ["IOSWebDriverClient"]
