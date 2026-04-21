"""
IOSDevice - 对应 packages/ios/src/device.ts

基于 WebDriverAgent HTTP API 的 iOS 设备适配器, 实现 ``AbstractInterface``.

与 JS 版差异:
- JS 版同时包含 WDA 生命周期管理 (`WDAManager`: 通过 xcodebuild 启 WDA),
  Python 版**不自动启动 WDA**, 假设 WDA 已在目标端口运行
  (用户可用 `tidevice xctest` / Xcode / 模拟器手动启动).
- UI 树: JS 同样返回空 (`getElementsInfo` / `getElementsNodeTree`), 走纯视觉
  方案, Python 这里也不解析 XCUITest XML.
"""

from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from ..core.types import ScreenshotItem, UIContext
from ..shared.env.constants import (
    DEFAULT_WDA_HOST,
    DEFAULT_WDA_PORT,
    MIDSCENE_WDA_BASE_URL,
    MIDSCENE_WDA_HOST,
    MIDSCENE_WDA_PORT,
    MIDSCENE_WDA_TIMEOUT,
)
from ..shared.logger import logger
from ..shared.types import Size
from ..web_integration.base import AbstractInterface
from .app_name_mapping import DEFAULT_APP_NAME_MAPPING, resolve_bundle_id
from .webdriver_client import IOSWebDriverClient


_URL_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")


@dataclass
class IOSDeviceOpt:
    """
    IOSDevice 可选参数. 对齐 JS `IOSDeviceOpt`.

    Attributes:
        wda_host: WDA host (默认 ``MIDSCENE_WDA_HOST`` 或 ``localhost``)
        wda_port: WDA port (默认 ``MIDSCENE_WDA_PORT`` 或 ``8100``)
        wda_base_url: 直接指定完整 URL, 覆盖 host/port
        wda_timeout: 单次 HTTP 请求超时 (秒)
        capabilities: 传给 createSession 的额外 capabilities
        auto_dismiss_keyboard: 输入完成后自动隐藏键盘
        app_name_mapping: 额外的 app 名 → bundle id 映射 (优先级高于默认)
        keyboard_dismiss_keys: 可选. 覆盖默认的 dismiss_keyboard 按钮名
    """

    wda_host: Optional[str] = None
    wda_port: Optional[int] = None
    wda_base_url: Optional[str] = None
    wda_timeout: float = 30.0
    capabilities: dict[str, Any] = field(default_factory=dict)
    auto_dismiss_keyboard: bool = True
    app_name_mapping: dict[str, str] = field(default_factory=dict)
    keyboard_dismiss_keys: Optional[list[str]] = None


# 默认 scroll-until 检测参数 (对齐 JS)
_MAX_SCROLL_ATTEMPTS = 20


class IOSDevice(AbstractInterface):
    """iOS 设备适配器."""

    interface_type = "ios"

    def __init__(
        self,
        options: Optional[IOSDeviceOpt] = None,
        client: Optional[IOSWebDriverClient] = None,
    ) -> None:
        """
        Args:
            options: IOSDeviceOpt.
            client: 测试用途可直接注入自定义 IOSWebDriverClient
                (带 mock transport 的 httpx 客户端).
        """
        self.options: IOSDeviceOpt = options or IOSDeviceOpt()

        host = (
            self.options.wda_host
            or os.environ.get(MIDSCENE_WDA_HOST)
            or DEFAULT_WDA_HOST
        )
        port_raw = (
            self.options.wda_port
            or os.environ.get(MIDSCENE_WDA_PORT)
            or DEFAULT_WDA_PORT
        )
        port = int(port_raw)
        base_url = self.options.wda_base_url or os.environ.get(
            MIDSCENE_WDA_BASE_URL
        )
        timeout = float(
            os.environ.get(MIDSCENE_WDA_TIMEOUT) or self.options.wda_timeout
        )

        self.wda = client or IOSWebDriverClient(
            host=host, port=port, base_url=base_url, timeout=timeout
        )

        self.device_id: str = "pending-connection"
        self.description: Optional[str] = None
        self.uri: Optional[str] = None
        self._device_pixel_ratio: float = 1.0
        self._dpr_initialized = False
        self._destroyed = False

        self._app_name_mapping: dict[str, str] = {
            **DEFAULT_APP_NAME_MAPPING,
            **self.options.app_name_mapping,
        }

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def set_app_name_mapping(self, mapping: dict[str, str]) -> None:
        """对齐 JS `setAppNameMapping`."""
        self._app_name_mapping = dict(mapping)

    async def connect(self) -> None:
        """创建 WDA session, 读取设备信息. 多次调用幂等."""
        if self._destroyed:
            raise RuntimeError(
                f"IOSDevice {self.device_id} has been destroyed"
            )
        if self.wda.session_id:
            return
        await self.wda.create_session(self.options.capabilities)
        info = await self.wda.get_device_info()
        if info and info.get("udid"):
            self.device_id = info["udid"]
        try:
            size = await self.get_size()
            self.description = (
                f"UDID: {self.device_id}\n"
                f"Name: {(info or {}).get('name', '')}\n"
                f"Model: {(info or {}).get('model', '')}\n"
                f"ScreenSize: {int(size['width'])}x{int(size['height'])} "
                f"(DPR: {size.get('dpr')})"
            )
        except Exception as exc:  # pragma: no cover
            logger.debug(f"IOS describe best-effort failed: {exc}")

    async def destroy(self) -> None:
        if self._destroyed:
            return
        self._destroyed = True
        try:
            await self.wda.delete_session()
        except Exception:
            pass
        await self.wda.aclose()

    def describe(self) -> str:
        return self.description or f"Device ID: {self.device_id}"

    # ------------------------------------------------------------------
    # 屏幕信息
    # ------------------------------------------------------------------

    async def _init_dpr(self) -> None:
        if self._dpr_initialized:
            return
        scale = await self.wda.get_screen_scale()
        if not scale or scale <= 0:
            logger.warning(
                "Failed to get DPR from WDA, defaulting to 1.0 "
                "(可能影响坐标精度)"
            )
            scale = 1.0
        self._device_pixel_ratio = float(scale)
        self._dpr_initialized = True

    async def get_size(self) -> Size:
        """返回 CSS (逻辑像素) 尺寸 + dpr. 对齐 JS `size()`."""
        await self._init_dpr()
        window = await self.wda.get_window_size()
        return {
            "width": float(window["width"]),
            "height": float(window["height"]),
            "dpr": self._device_pixel_ratio,
        }

    # ------------------------------------------------------------------
    # 截图
    # ------------------------------------------------------------------

    async def screenshot(self, full_page: bool = False) -> str:
        """返回 base64 PNG. 对齐 JS `screenshotBase64`."""
        _ = full_page
        return await self.wda.take_screenshot()

    # ------------------------------------------------------------------
    # 基础触控 - AbstractInterface 合约
    # ------------------------------------------------------------------

    async def click(self, x: float, y: float) -> None:
        await self.wda.tap(round(x), round(y))

    async def double_click(self, x: float, y: float) -> None:
        await self.wda.double_tap(round(x), round(y))

    async def long_press(
        self, x: float, y: float, duration: int = 1000
    ) -> None:
        await self.wda.long_press(round(x), round(y), duration_ms=duration)

    async def hover(self, x: float, y: float) -> None:
        """触屏设备无 hover, 占位 no-op."""
        return None

    async def swipe(
        self,
        from_x: float,
        from_y: float,
        to_x: float,
        to_y: float,
        duration_ms: int = 500,
    ) -> None:
        await self.wda.swipe(
            round(from_x),
            round(from_y),
            round(to_x),
            round(to_y),
            duration_ms=duration_ms,
        )

    async def drag_and_drop(
        self,
        from_xy: tuple[float, float],
        to_xy: tuple[float, float],
    ) -> None:
        await self.swipe(from_xy[0], from_xy[1], to_xy[0], to_xy[1], 600)

    # ------------------------------------------------------------------
    # 滚动
    # ------------------------------------------------------------------

    async def scroll(
        self,
        direction: str,
        distance: Optional[int] = None,
    ) -> None:
        """
        单次滚动. direction: ``up`` / ``down`` / ``left`` / ``right``.

        语义: direction 指"屏幕内容移动方向" -- down 表示向下滚动更多内容
        (手指上滑).
        """
        direction = (direction or "down").lower()
        if direction not in ("up", "down", "left", "right"):
            raise ValueError(f"Unknown scroll direction: {direction}")

        size = await self.get_size()
        width = int(size["width"])
        height = int(size["height"])

        sx = width // 2
        sy = height // 2

        if direction in ("up", "down"):
            d = int(distance) if distance else height // 3
            dy = d if direction == "up" else -d  # up: content down → swipe down
            ex, ey = sx, sy + dy
        else:
            d = int(distance) if distance else int(width * 0.7)
            # left: bring left content into view → swipe finger right
            dx = d if direction == "left" else -d
            ex, ey = sx + dx, sy

        await self.wda.swipe(sx, sy, ex, ey, duration_ms=500)

    async def _scroll_until_boundary(
        self,
        direction: str,
        start_point: Optional[tuple[float, float]] = None,
        max_unchanged: int = 1,
    ) -> None:
        """
        基于截图对比的到头检测. 对齐 JS `scrollUntilBoundary`.
        """
        size = await self.get_size()
        width = int(size["width"])
        height = int(size["height"])
        if start_point:
            sx = round(start_point[0])
            sy = round(start_point[1])
        else:
            anchor = {
                "up": (width // 2, int(height * 0.2)),
                "down": (width // 2, int(height * 0.8)),
                "left": (int(width * 0.8), height // 2),
                "right": (int(width * 0.2), height // 2),
            }[direction]
            sx, sy = anchor

        last_shot: Optional[str] = None
        unchanged = 0

        for i in range(_MAX_SCROLL_ATTEMPTS):
            await asyncio.sleep(0.5)
            try:
                current = await self.screenshot()
            except Exception as exc:
                logger.debug(f"scroll boundary screenshot fail #{i}: {exc}")
                await asyncio.sleep(0.3)
                continue

            if last_shot and _screenshots_similar(last_shot, current, 10.0):
                unchanged += 1
                if unchanged >= max_unchanged:
                    logger.debug(
                        f"Reached {direction} boundary after {i + 1} attempts"
                    )
                    return
            else:
                unchanged = 0
            if i >= 15 and unchanged == 0:
                return
            last_shot = current

            scroll_distance = round(
                width * 0.6
                if direction in ("left", "right")
                else height * 0.6
            )
            if direction == "up":
                await self.wda.swipe(sx, sy, sx, sy + scroll_distance, 300)
            elif direction == "down":
                await self.wda.swipe(sx, sy, sx, sy - scroll_distance, 300)
            elif direction == "left":
                await self.wda.swipe(sx, sy, sx + scroll_distance, sy, 300)
            elif direction == "right":
                await self.wda.swipe(sx, sy, sx - scroll_distance, sy, 300)
            await asyncio.sleep(2.0)

    async def scroll_until_top(
        self, start_point: Optional[tuple[float, float]] = None
    ) -> None:
        await self._scroll_until_boundary("up", start_point, 1)

    async def scroll_until_bottom(
        self, start_point: Optional[tuple[float, float]] = None
    ) -> None:
        await self._scroll_until_boundary("down", start_point, 1)

    async def scroll_until_left(
        self, start_point: Optional[tuple[float, float]] = None
    ) -> None:
        await self._scroll_until_boundary("left", start_point, 1)

    async def scroll_until_right(
        self, start_point: Optional[tuple[float, float]] = None
    ) -> None:
        await self._scroll_until_boundary("right", start_point, 3)

    # ------------------------------------------------------------------
    # 键盘 / 输入
    # ------------------------------------------------------------------

    async def key_press(self, key: str) -> None:
        await self.wda.press_key(key)

    async def input_text(
        self,
        text: str,
        x: Optional[float] = None,
        y: Optional[float] = None,
        clear_first: bool = False,
    ) -> None:
        """
        AbstractInterface 合约的输入.

        - x/y 提供 → 先 tap 以聚焦
        - clear_first → 先清空焦点输入框 (WDA `/element/{id}/clear`)
        - 输入后若 `auto_dismiss_keyboard=True` 则尝试关闭软键盘
        """
        if x is not None and y is not None:
            await self.click(x, y)
            await asyncio.sleep(0.15)

        if clear_first:
            await self.clear_input()

        if text:
            await asyncio.sleep(0.2)
            await self.wda.type_text(text)
            await asyncio.sleep(0.3)
            if self.options.auto_dismiss_keyboard:
                await self.hide_keyboard()

    async def type_text(self, text: str) -> None:
        """直接输入文本 (已聚焦输入框). 名字和 WDA 一致."""
        await self.wda.type_text(text)

    async def clear_input(self) -> bool:
        """
        清空当前焦点输入框. 对齐 JS `clearInput` 的纯输入部分.

        Returns:
            是否清空成功.
        """
        return await self.wda.clear_active_element()

    async def hide_keyboard(self) -> bool:
        """对齐 JS `hideKeyboard`."""
        keys = self.options.keyboard_dismiss_keys or [
            "return",
            "done",
            "go",
            "search",
            "next",
            "send",
        ]
        ok = await self.wda.dismiss_keyboard(keys)
        if ok:
            await asyncio.sleep(0.3)
            return True

        # fallback: 上滑手势
        try:
            size = await self.wda.get_window_size()
            cx = size["width"] // 2
            sy = int(size["height"] * 0.9)
            ey = int(size["height"] * 0.5)
            await self.wda.swipe(cx, sy, cx, ey, duration_ms=300)
            await asyncio.sleep(0.3)
            return True
        except Exception as exc:
            logger.debug(f"hide_keyboard fallback failed: {exc}")
            return False

    # ------------------------------------------------------------------
    # iOS 专属动作
    # ------------------------------------------------------------------

    async def launch(self, uri: str) -> "IOSDevice":
        """
        启动 app 或打开 URL. 对齐 JS `launch`.

        - 含 scheme (例如 ``https://``, ``mailto:``, ``tbopen://``) → 走 URL
        - 其它当作 bundle id / app 名 (查 mapping)
        """
        if not uri or not uri.strip():
            raise ValueError("launch requires a non-empty uri")
        self.uri = uri
        if _URL_SCHEME_RE.match(uri):
            await self.wda.open_url(uri)
        else:
            resolved = resolve_bundle_id(uri, self._app_name_mapping) or uri
            await self.wda.launch_app(resolved)
        return self

    async def activate_app(self, bundle_id: str) -> None:
        resolved = resolve_bundle_id(bundle_id, self._app_name_mapping) or bundle_id
        await self.wda.activate_app(resolved)

    async def terminate_app(self, bundle_id: str) -> None:
        resolved = resolve_bundle_id(bundle_id, self._app_name_mapping) or bundle_id
        await self.wda.terminate_app(resolved)

    async def home(self) -> None:
        """系统 Home. 对齐 JS `home`."""
        await self.wda.press_home_button()

    async def app_switcher(self) -> None:
        """应用切换器. 对齐 JS `appSwitcher`."""
        await self.wda.app_switcher()

    async def run_wda_request(
        self, method: str, endpoint: str, data: Optional[dict[str, Any]] = None
    ) -> Any:
        """
        直接调 WDA HTTP 接口. 对齐 JS `runWdaRequest`.

        method 应为 GET/POST/DELETE/PUT.
        """
        method_upper = method.upper()
        if method_upper not in ("GET", "POST", "DELETE", "PUT"):
            raise ValueError(f"Unsupported HTTP method for WDA: {method}")
        return await self.wda.execute_request(method_upper, endpoint, data)

    # ------------------------------------------------------------------
    # AbstractInterface 的 Web 方法 - iOS 上的合理行为
    # ------------------------------------------------------------------

    async def wait_for_navigation(self, timeout: Optional[int] = None) -> None:
        await asyncio.sleep(0.3)

    async def wait_for_network_idle(self, timeout: Optional[int] = None) -> None:
        await asyncio.sleep(0.3)

    async def evaluate_javascript(self, script: str) -> Any:
        """
        把 agent 层会下发的几个 web 模式转译到原生 iOS 操作.

        - ``window.scrollTo(0, 0)`` → scroll_until_top
        - ``...document.body.scrollHeight`` → scroll_until_bottom
        - ``window.history.back()`` → home (iOS 无通用 back 手势)
        """
        if not script:
            return None
        s = script.strip()
        if "window.scrollTo(0, 0)" in s:
            await self.scroll_until_top()
            return None
        if "document.body.scrollHeight" in s:
            await self.scroll_until_bottom()
            return None
        if "window.history.back" in s:
            await self.home()
            return None
        logger.debug(f"evaluate_javascript ignored on iOS: {s[:80]}")
        return None

    # ------------------------------------------------------------------
    # get_ui_context
    # ------------------------------------------------------------------

    async def get_ui_context(self) -> UIContext:
        screenshot_data = await self.screenshot()
        size = await self.get_size()

        class IOSUIContext(UIContext):
            def __init__(self, screenshot: ScreenshotItem, size: Size):
                self.screenshot = screenshot
                self.size = size
                self._is_frozen = False

        return IOSUIContext(
            screenshot=ScreenshotItem(screenshot_data),
            size=size,
        )


def _screenshots_similar(a: str, b: str, tolerance_percent: float) -> bool:
    """
    粗略截图相似度. 对齐 JS `compareScreenshots`.

    - 长度差 > 10% 认为不同.
    - 否则前 2000 字符的字符差分率 <= tolerance_percent 视为相似.
    """
    if a == b:
        return True
    la, lb = len(a), len(b)
    if la == 0 or lb == 0:
        return False
    if abs(la - lb) > min(la, lb) * 0.1:
        return False
    sample = min(2000, min(la, lb))
    diff = sum(1 for i in range(sample) if a[i] != b[i])
    return (diff / sample) * 100 <= tolerance_percent


__all__ = ["IOSDevice", "IOSDeviceOpt"]
