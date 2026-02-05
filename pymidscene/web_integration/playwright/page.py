"""
Playwright 页面适配器 - 对应 packages/web-integration/src/playwright/page.ts

将 Playwright Page 适配为 PyMidscene 的统一接口。
"""

from typing import Optional, Any
import base64
import asyncio

from playwright.async_api import Page as PlaywrightPage

from ..base import AbstractInterface
from ...core.types import UIContext, ScreenshotItem
from ...shared.types import Size
from ...shared.logger import logger


class WebPage(AbstractInterface):
    """Playwright 页面适配器"""

    # 默认配置
    DEFAULT_WAIT_FOR_NAVIGATION_TIMEOUT = 10000  # 10 秒
    DEFAULT_WAIT_FOR_NETWORK_IDLE_TIMEOUT = 10000  # 10 秒

    def __init__(
        self,
        page: PlaywrightPage,
        wait_for_navigation_timeout: Optional[int] = None,
        wait_for_network_idle_timeout: Optional[int] = None,
    ):
        """
        初始化 Playwright 页面适配器

        Args:
            page: Playwright Page 实例
            wait_for_navigation_timeout: 导航超时时间（毫秒）
            wait_for_network_idle_timeout: 网络空闲超时时间（毫秒）
        """
        self.page = page
        self.wait_for_navigation_timeout = (
            wait_for_navigation_timeout or self.DEFAULT_WAIT_FOR_NAVIGATION_TIMEOUT
        )
        self.wait_for_network_idle_timeout = (
            wait_for_network_idle_timeout or self.DEFAULT_WAIT_FOR_NETWORK_IDLE_TIMEOUT
        )

        logger.debug(
            f"WebPage initialized: "
            f"nav_timeout={self.wait_for_navigation_timeout}ms, "
            f"idle_timeout={self.wait_for_network_idle_timeout}ms"
        )

    async def get_ui_context(self) -> UIContext:
        """获取当前 UI 上下文"""
        screenshot_data = await self.screenshot()
        size = await self.get_size()

        # 创建 UIContext（简化版，完整实现需要更多字段）
        class WebUIContext(UIContext):
            def __init__(self, screenshot: ScreenshotItem, size: Size):
                self.screenshot = screenshot
                self.size = size
                self._is_frozen = False

        return WebUIContext(
            screenshot=ScreenshotItem(screenshot_data),
            size=size
        )

    async def get_size(self) -> Size:
        """获取视口尺寸"""
        viewport = self.page.viewport_size
        if viewport is None:
            # 如果没有设置 viewport，尝试获取窗口尺寸
            size_info = await self.page.evaluate(
                "() => ({ width: window.innerWidth, height: window.innerHeight })"
            )
            return {
                "width": float(size_info["width"]),
                "height": float(size_info["height"]),
                "dpr": None
            }

        return {
            "width": float(viewport["width"]),
            "height": float(viewport["height"]),
            "dpr": None
        }

    async def screenshot(self, full_page: bool = False) -> str:
        """
        获取截图（Base64 编码）

        Args:
            full_page: 是否截取完整页面

        Returns:
            Base64 编码的图像字符串
        """
        logger.debug(f"Taking screenshot: full_page={full_page}")

        # 截图
        screenshot_bytes = await self.page.screenshot(
            type="png",
            full_page=full_page
        )

        # 转换为 Base64
        screenshot_base64 = base64.b64encode(screenshot_bytes).decode('utf-8')

        logger.debug(f"Screenshot taken: size={len(screenshot_base64)} chars")

        return screenshot_base64

    async def click(self, x: float, y: float) -> None:
        """
        点击指定坐标

        Args:
            x: X 坐标
            y: Y 坐标
        """
        logger.debug(f"Clicking at ({x}, {y})")

        await self.page.mouse.click(x, y)

        # 等待可能的导航
        await self.wait_for_navigation()

    async def input_text(
        self,
        text: str,
        x: Optional[float] = None,
        y: Optional[float] = None,
        clear_first: bool = True
    ) -> None:
        """
        输入文本

        Args:
            text: 要输入的文本
            x: 可选的 X 坐标（先点击再输入）
            y: 可选的 Y 坐标（先点击再输入）
            clear_first: 是否先清空输入框（默认 True，与 JS 版本一致）
        """
        logger.debug(f"Inputting text: '{text}' at ({x}, {y}), clear_first={clear_first}")

        # 如果提供了坐标，先点击
        if x is not None and y is not None:
            # 使用 mouse.click 而不是 self.click，避免等待导航
            await self.page.mouse.click(x, y)
            # 等待元素聚焦
            await asyncio.sleep(0.1)

        # 清空输入框内容（与 JS 版本一致）
        if clear_first:
            # 方法1: 全选后删除 (跨平台兼容)
            # 使用 Ctrl+A (Windows/Linux) 或 Meta+A (macOS) 全选
            try:
                # 尝试使用 Playwright 的 fill 方法定位到当前焦点元素
                # 先全选现有内容
                await self.page.keyboard.press("Control+a")
                await asyncio.sleep(0.05)
                # 删除选中内容
                await self.page.keyboard.press("Backspace")
                await asyncio.sleep(0.05)
            except Exception as e:
                logger.debug(f"Clear with Ctrl+A failed, trying alternative: {e}")
                # 备用方法：多次退格清除
                # 先移动到末尾，然后逐个删除
                await self.page.keyboard.press("End")
                for _ in range(100):  # 最多清除100个字符
                    await self.page.keyboard.press("Backspace")

        # 输入文本
        await self.page.keyboard.type(text)

    async def hover(self, x: float, y: float) -> None:
        """
        悬停到指定坐标

        Args:
            x: X 坐标
            y: Y 坐标
        """
        logger.debug(f"Hovering at ({x}, {y})")

        await self.page.mouse.move(x, y)

    async def scroll(
        self,
        direction: str,
        distance: Optional[int] = None
    ) -> None:
        """
        滚动页面

        Args:
            direction: 滚动方向（up/down/left/right）
            distance: 滚动距离（像素），默认为视口高度
        """
        logger.debug(f"Scrolling {direction}, distance={distance}")

        if distance is None:
            # 默认滚动一个视口的高度
            size = await self.get_size()
            distance = int(size["height"])

        # 根据方向计算滚动量
        delta_x = 0
        delta_y = 0

        if direction == "down":
            delta_y = distance
        elif direction == "up":
            delta_y = -distance
        elif direction == "right":
            delta_x = distance
        elif direction == "left":
            delta_x = -distance
        else:
            raise ValueError(f"Invalid scroll direction: {direction}")

        # 执行滚动
        await self.page.evaluate(
            f"window.scrollBy({delta_x}, {delta_y})"
        )

        # 等待滚动完成
        await asyncio.sleep(0.3)

    async def key_press(self, key: str) -> None:
        """
        按键

        Args:
            key: 按键名称（Enter、Escape 等）
        """
        logger.debug(f"Pressing key: {key}")

        await self.page.keyboard.press(key)

        # 等待可能的导航（如按 Enter 提交表单）
        await self.wait_for_navigation()

    async def wait_for_navigation(self, timeout: Optional[int] = None) -> None:
        """
        等待导航完成

        Args:
            timeout: 超时时间（毫秒）
        """
        timeout_ms = timeout or self.wait_for_navigation_timeout

        if timeout_ms == 0:
            logger.debug("Navigation timeout is 0, skipping wait")
            return

        logger.debug(f"Waiting for navigation (timeout={timeout_ms}ms)")

        try:
            # 等待 HTML 元素存在（表示页面已加载）
            await self.page.wait_for_selector(
                "html",
                timeout=timeout_ms
            )
        except Exception as e:
            logger.warning(
                f"Waiting for navigation timed out, but continuing execution: {e}"
            )

    async def wait_for_network_idle(self, timeout: Optional[int] = None) -> None:
        """
        等待网络空闲

        Args:
            timeout: 超时时间（毫秒）
        """
        timeout_ms = timeout or self.wait_for_network_idle_timeout

        if timeout_ms == 0:
            logger.debug("Network idle timeout is 0, skipping wait")
            return

        logger.debug(f"Waiting for network idle (timeout={timeout_ms}ms)")

        try:
            # Playwright 的网络空闲等待
            await self.page.wait_for_load_state(
                "networkidle",
                timeout=timeout_ms
            )
        except Exception as e:
            logger.warning(
                f"Waiting for network idle timed out, but continuing execution: {e}"
            )

    async def evaluate_javascript(self, script: str) -> Any:
        """
        执行 JavaScript 代码

        Args:
            script: JavaScript 代码

        Returns:
            执行结果
        """
        logger.debug(f"Evaluating JavaScript: {script[:100]}...")

        result = await self.page.evaluate(script)

        logger.debug(f"JavaScript evaluation result: {str(result)[:100]}...")

        return result

    async def wait(self, timeout_ms: int) -> None:
        """
        等待指定时间

        Args:
            timeout_ms: 等待时间（毫秒）
        """
        logger.debug(f"Waiting for {timeout_ms}ms")
        await asyncio.sleep(timeout_ms / 1000)

    # ==================== XPath 相关方法（与 JS 版本对齐） ====================

    async def get_element_xpath(self, x: float, y: float) -> Optional[str]:
        """
        获取指定坐标处元素的 XPath

        Args:
            x: X 坐标
            y: Y 坐标

        Returns:
            元素的 XPath 路径，如果找不到则返回 None
        """
        logger.debug(f"Getting XPath for element at ({x}, {y})")

        # JavaScript 代码：获取坐标处元素的 XPath
        xpath = await self.page.evaluate("""
            (coords) => {
                const { x, y } = coords;
                const element = document.elementFromPoint(x, y);
                if (!element) return null;

                // 生成 XPath 的函数
                function getXPath(el) {
                    if (!el || el.nodeType !== Node.ELEMENT_NODE) return '';
                    
                    // 如果有 ID，使用 ID 定位（更稳定）
                    // 注意：JS 版本不使用 ID，我们也保持一致
                    
                    const parts = [];
                    let current = el;
                    
                    while (current && current.nodeType === Node.ELEMENT_NODE) {
                        let index = 1;
                        let sibling = current.previousElementSibling;
                        
                        while (sibling) {
                            if (sibling.nodeName === current.nodeName) {
                                index++;
                            }
                            sibling = sibling.previousElementSibling;
                        }
                        
                        const tagName = current.nodeName.toLowerCase();
                        parts.unshift(`${tagName}[${index}]`);
                        current = current.parentElement;
                    }
                    
                    return '/' + parts.join('/');
                }

                return getXPath(element);
            }
        """, {"x": x, "y": y})

        if xpath:
            logger.debug(f"XPath found: {xpath}")
        else:
            logger.warning(f"No element found at ({x}, {y})")

        return xpath

    async def get_element_by_xpath(self, xpath: str) -> Optional[dict]:
        """
        通过 XPath 获取元素信息（边界框和中心点）

        Args:
            xpath: 元素的 XPath 路径

        Returns:
            包含 bbox 和 center 的字典，如果找不到则返回 None
        """
        logger.debug(f"Getting element by XPath: {xpath}")

        try:
            # 使用 Playwright 的 locator 通过 XPath 定位
            locator = self.page.locator(f"xpath={xpath}")
            
            # 检查元素是否存在
            count = await locator.count()
            if count == 0:
                logger.warning(f"Element not found for XPath: {xpath}")
                return None

            # 获取第一个匹配元素的边界框
            bounding_box = await locator.first.bounding_box()
            
            if bounding_box is None:
                logger.warning(f"Element has no bounding box: {xpath}")
                return None

            # 计算中心点
            center_x = bounding_box["x"] + bounding_box["width"] / 2
            center_y = bounding_box["y"] + bounding_box["height"] / 2

            result = {
                "bbox": [
                    bounding_box["x"],
                    bounding_box["y"],
                    bounding_box["x"] + bounding_box["width"],
                    bounding_box["y"] + bounding_box["height"]
                ],
                "center": [center_x, center_y],
                "rect": {
                    "left": bounding_box["x"],
                    "top": bounding_box["y"],
                    "width": bounding_box["width"],
                    "height": bounding_box["height"]
                }
            }

            logger.debug(f"Element found: center=({center_x}, {center_y})")
            return result

        except Exception as e:
            logger.warning(f"Failed to get element by XPath: {xpath}, error: {e}")
            return None

    async def click_by_xpath(self, xpath: str) -> bool:
        """
        通过 XPath 点击元素

        Args:
            xpath: 元素的 XPath 路径

        Returns:
            是否成功点击
        """
        logger.debug(f"Clicking element by XPath: {xpath}")

        try:
            locator = self.page.locator(f"xpath={xpath}")
            await locator.first.click()
            await self.wait_for_navigation()
            return True
        except Exception as e:
            logger.warning(f"Failed to click by XPath: {xpath}, error: {e}")
            return False

    async def input_by_xpath(self, xpath: str, text: str, clear_first: bool = True) -> bool:
        """
        通过 XPath 在元素中输入文本

        Args:
            xpath: 元素的 XPath 路径
            text: 要输入的文本
            clear_first: 是否先清空

        Returns:
            是否成功输入
        """
        logger.debug(f"Inputting text by XPath: {xpath}, text: '{text}'")

        try:
            locator = self.page.locator(f"xpath={xpath}")
            
            if clear_first:
                await locator.first.fill(text)
            else:
                await locator.first.type(text)
            
            return True
        except Exception as e:
            logger.warning(f"Failed to input by XPath: {xpath}, error: {e}")
            return False


__all__ = ["WebPage"]
