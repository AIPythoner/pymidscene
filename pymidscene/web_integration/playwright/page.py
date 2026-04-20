"""
Playwright 页面适配器 - 对应 packages/web-integration/src/playwright/page.ts

将 Playwright Page 适配为 PyMidscene 的统一接口。
"""

from typing import Optional, Any, List, Tuple
import base64
import asyncio
import sys

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
            wait_for_navigation_timeout
            if wait_for_navigation_timeout is not None
            else self.DEFAULT_WAIT_FOR_NAVIGATION_TIMEOUT
        )
        self.wait_for_network_idle_timeout = (
            wait_for_network_idle_timeout
            if wait_for_network_idle_timeout is not None
            else self.DEFAULT_WAIT_FOR_NETWORK_IDLE_TIMEOUT
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
        """
        获取视口尺寸 (CSS 像素) 并附带真实 devicePixelRatio.

        对应 JS base-page.ts:316-327,与 JS 保持同样的契约:
        width/height 为 CSS 像素,dpr 用于还原图像像素 → CSS 的缩放关系.
        HiDPI 屏幕下若 dpr 未返回,所有归一化-to-像素/像素 直通路径都会
        产生系统性点击偏移,因此这里总是读取真实值.
        """
        size_info = await self.page.evaluate(
            """
            () => ({
                width: window.innerWidth,
                height: window.innerHeight,
                dpr: window.devicePixelRatio || 1
            })
            """
        )
        return {
            "width": float(size_info["width"]),
            "height": float(size_info["height"]),
            "dpr": float(size_info.get("dpr") or 1)
        }

    async def screenshot(self, full_page: bool = False) -> str:
        """
        获取截图(JPEG q=90 + raw base64,与 JS base-page.ts `screenshotBase64` 对齐).

        历史:之前用 PNG 返回 —— 相同内容下 PNG 体积是 JPEG q=90 的 3-5 倍,
        直接意味着 AI 请求的 image token 成本高 3-5 倍.JS 版本用 JPEG q=90 是
        midscene 的既定选择,这里对齐.

        返回格式:仍是**纯 base64**,不带 `data:image/jpeg;base64,` 前缀.调用方
        (agent._build_messages 和 SessionRecorder)会在需要时自行加前缀,这样
        既不破坏现有 call sites,又保持跨调用的数据紧凑.

        Args:
            full_page: 是否截取完整页面

        Returns:
            JPEG 图像的 Base64 字符串(无 data: 前缀)
        """
        logger.debug(f"Taking screenshot: full_page={full_page}")

        screenshot_bytes = await self.page.screenshot(
            type="jpeg",
            quality=90,
            full_page=full_page,
        )
        screenshot_base64 = base64.b64encode(screenshot_bytes).decode('utf-8')

        logger.debug(f"Screenshot taken: size={len(screenshot_base64)} chars (jpeg)")
        return screenshot_base64

    async def _ensure_in_viewport(self, x: float, y: float) -> Tuple[float, float]:
        """
        如果 (x, y) 已在视口内则直接返回;否则做一次粗滚动把 y 居中,
        然后返回调整后的 (x, y_in_viewport).

        **不做 `elementFromPoint` → `getBoundingClientRect` 的"重取中心"**:
        agent 层已经通过 XPath 预先 `scrollIntoView({block:'center'})` 并
        刷新过 element.center;在这里再根据 `elementFromPoint` 重新定位
        可能命中覆盖的 wrapper/overlay,偏离 AI 实际看到的像素点.
        """
        adjusted = await self.page.evaluate(
            """
            (coords) => {
                const { x, y } = coords;
                const inViewport = (
                    x >= 0 && x <= window.innerWidth &&
                    y >= 0 && y <= window.innerHeight
                );
                if (inViewport) {
                    return { x, y, scrolled: false };
                }
                // 元素完全在视口外 —— 粗滚动把 y 居中再点
                window.scrollTo({
                    top: Math.max(0, y - window.innerHeight / 2),
                    behavior: 'instant'
                });
                return { x, y: y - window.scrollY, scrolled: true };
            }
            """,
            {"x": x, "y": y},
        )
        if adjusted and adjusted.get("scrolled"):
            await asyncio.sleep(0.15)
        return (adjusted["x"], adjusted["y"]) if adjusted else (x, y)

    async def click(self, x: float, y: float) -> None:
        """
        点击指定坐标.

        Args:
            x: X 坐标 (CSS 像素,相对文档左上角)
            y: Y 坐标 (CSS 像素,相对文档左上角)
        """
        logger.debug(f"Clicking at ({x}, {y})")

        click_x, click_y = await self._ensure_in_viewport(x, y)
        await self.page.mouse.click(click_x, click_y)

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
        
        🔑 关键：输入前总是将元素滚动到视口中心

        Args:
            text: 要输入的文本
            x: 可选的 X 坐标（先点击再输入）
            y: 可选的 Y 坐标（先点击再输入）
            clear_first: 是否先清空输入框（默认 True，与 JS 版本一致）
        """
        logger.debug(f"Inputting text: '{text}' at ({x}, {y}), clear_first={clear_first}")

        # 如果提供了坐标,聚焦到该点(agent 层已经 scrollIntoView,这里只做视口兜底)
        if x is not None and y is not None:
            click_x, click_y = await self._ensure_in_viewport(x, y)
            await self.page.mouse.click(click_x, click_y)
            await asyncio.sleep(0.1)

        # 清空输入框内容(跨平台: mac 使用 Meta+A,其他平台 Ctrl+A —— 与 JS base-page.ts:481-504 对齐)
        if clear_first:
            is_mac = sys.platform == "darwin"
            select_all_chord = "Meta+a" if is_mac else "Control+a"
            try:
                await self.page.keyboard.press(select_all_chord)
                await asyncio.sleep(0.05)
                await self.page.keyboard.press("Backspace")
                await asyncio.sleep(0.05)
            except Exception as e:
                logger.debug(f"Clear with {select_all_chord} failed, falling back: {e}")
                # 备用方法: 多次退格清除
                await self.page.keyboard.press("End")
                for _ in range(100):
                    await self.page.keyboard.press("Backspace")

        # 输入文本 —— delay=80ms 对齐 JS base-page.ts:447,避免受控输入框丢字
        await self.page.keyboard.type(text, delay=80)

    async def double_click(self, x: float, y: float) -> None:
        """
        双击坐标。对应 JS base-page.ts `leftDoubleClick`。
        """
        logger.debug(f"Double-clicking at ({x}, {y})")
        cx, cy = await self._ensure_in_viewport(x, y)
        await self.page.mouse.dblclick(cx, cy)
        await self.wait_for_navigation()

    async def right_click(self, x: float, y: float) -> None:
        """
        右键点击坐标。对应 JS base-page.ts `rightClick`。
        """
        logger.debug(f"Right-clicking at ({x}, {y})")
        cx, cy = await self._ensure_in_viewport(x, y)
        await self.page.mouse.click(cx, cy, button="right")

    async def drag_and_drop(
        self,
        from_x: float,
        from_y: float,
        to_x: float,
        to_y: float,
    ) -> None:
        """
        拖放操作。对应 JS base-page.ts `dragAndDrop`。
        Playwright 原生无单步 drag-and-drop API,用 mouse.move → down → move → up 组合。
        """
        logger.debug(f"Drag from ({from_x}, {from_y}) to ({to_x}, {to_y})")
        fx, fy = await self._ensure_in_viewport(from_x, from_y)
        tx, ty = await self._ensure_in_viewport(to_x, to_y)
        await self.page.mouse.move(fx, fy)
        await self.page.mouse.down()
        # 分段 move 让浏览器 dispatch dragover 事件
        steps = 10
        for i in range(1, steps + 1):
            ix = fx + (tx - fx) * (i / steps)
            iy = fy + (ty - fy) * (i / steps)
            await self.page.mouse.move(ix, iy)
            await asyncio.sleep(0.02)
        await self.page.mouse.up()
        await self.wait_for_navigation()

    async def hover(self, x: float, y: float) -> None:
        """
        悬停到指定坐标.

        Args:
            x: X 坐标 (CSS 像素)
            y: Y 坐标 (CSS 像素)
        """
        logger.debug(f"Hovering at ({x}, {y})")

        hover_x, hover_y = await self._ensure_in_viewport(x, y)
        await self.page.mouse.move(hover_x, hover_y)

    async def scroll(
        self,
        direction: str,
        distance: Optional[int] = None,
        starting_point: Optional[dict] = None
    ) -> None:
        """
        滚动页面（与 JS 版本对齐，使用 mouse.wheel）

        JS 版本使用 mouse.wheel 而非 window.scrollBy，这是关键区别：
        - mouse.wheel 会滚动鼠标指针下方的实际可滚动容器（如 SPA 内部的 div）
        - window.scrollBy 只滚动主文档窗口，对内部滚动容器无效

        对应 JS: base-page.ts scrollDown/scrollUp/scrollLeft/scrollRight

        Args:
            direction: 滚动方向（up/down/left/right）
            distance: 滚动距离（像素），默认为视口高度的 70%（与 JS 版本一致）
            starting_point: 滚动起点坐标 {"x": ..., "y": ...}，默认为视口中心
        """
        logger.debug(f"Scrolling {direction}, distance={distance}")

        if distance is None:
            # 默认滚动视口高度的 70%（与 JS 版本 innerHeight * 0.7 对齐）
            size = await self.get_size()
            if direction in ("up", "down"):
                distance = int(size["height"] * 0.7)
            else:
                distance = int(size["width"] * 0.7)

        # 滚动前先移动鼠标到指定位置或视口中心
        # 对应 JS: moveToPointBeforeScroll()
        if starting_point:
            await self.page.mouse.move(starting_point["x"], starting_point["y"])
        else:
            size = await self.get_size()
            center_x = int(size["width"] / 2)
            center_y = int(size["height"] / 2)
            await self.page.mouse.move(center_x, center_y)

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

        # 使用 mouse.wheel 滚动（与 JS 版本完全一致）
        await self.page.mouse.wheel(delta_x, delta_y)

        # 等待滚动完成（与 JS 版本 sleep(500) 对齐）
        await asyncio.sleep(0.5)

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
        timeout_ms = (
            timeout if timeout is not None else self.wait_for_navigation_timeout
        )

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
        timeout_ms = (
            timeout if timeout is not None else self.wait_for_network_idle_timeout
        )

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

    async def get_element_xpaths(self, x: float, y: float) -> List[str]:
        """
        Return **multiple** XPath candidates for the element at ``(x, y)``.

        M1: a single ``tag[n]`` path is brittle — one sibling insertion
        shifts all indices and cache misses. We return several fallback
        candidates in priority order so cache hits survive minor DOM drift:

        1. ``//tag[@id='...']`` if the element has an id
        2. ``//tag[@data-testid='...']`` / ``[@aria-label='...']`` etc.
        3. ``//tag[normalize-space(text())='<text>']`` when the element has
           short stable text
        4. the full ``/html/body/.../tag[n]`` tag-indexed path (legacy fallback)

        Mirrors (loosely) JS ``getXpathsByPoint`` from
        ``@midscene/shared/extractor`` which also returns a ranked list.
        """
        logger.debug(f"Getting XPath candidates for element at ({x}, {y})")

        xpaths: List[str] = await self.page.evaluate(
            """
            (coords) => {
                const { x, y } = coords;
                const el = document.elementFromPoint(x, y);
                if (!el) return [];

                const results = [];

                const escAttr = (v) => String(v).replace(/'/g, "\\\\'");
                const tag = el.nodeName.toLowerCase();

                // 1. id
                if (el.id && /^[A-Za-z][\\w\\-:.]*$/.test(el.id)) {
                    results.push(`//${tag}[@id='${escAttr(el.id)}']`);
                }
                // 2. test/a11y attrs
                for (const attr of ['data-testid','data-test-id','data-test','aria-label','name','role']) {
                    const v = el.getAttribute(attr);
                    if (v && v.length <= 80) {
                        results.push(`//${tag}[@${attr}='${escAttr(v)}']`);
                    }
                }
                // 3. short stable text
                const text = (el.textContent || '').trim();
                if (text && text.length <= 40 && /\\S/.test(text)) {
                    const oneLine = text.replace(/\\s+/g, ' ');
                    results.push(`//${tag}[normalize-space(text())='${escAttr(oneLine)}']`);
                }

                // 4. full tag[n] path (always include as last-ditch fallback)
                const parts = [];
                let cur = el;
                while (cur && cur.nodeType === Node.ELEMENT_NODE) {
                    let idx = 1;
                    let sib = cur.previousElementSibling;
                    while (sib) {
                        if (sib.nodeName === cur.nodeName) idx++;
                        sib = sib.previousElementSibling;
                    }
                    parts.unshift(`${cur.nodeName.toLowerCase()}[${idx}]`);
                    cur = cur.parentElement;
                }
                results.push('/' + parts.join('/'));

                // Dedup preserving order
                const seen = new Set();
                return results.filter(p => {
                    if (seen.has(p)) return false;
                    seen.add(p);
                    return true;
                });
            }
            """,
            {"x": x, "y": y},
        )
        if xpaths:
            logger.debug(f"XPath candidates ({len(xpaths)}): {xpaths[0][:80]}...")
        return xpaths or []

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

    async def scroll_element_into_view(
        self,
        x: float,
        y: float,
        block: str = 'center',
        behavior: str = 'instant'
    ) -> bool:
        """
        将指定坐标的元素滚动到视口中
        
        对应 JS 版本: node.scrollIntoView({ behavior: 'instant', block: 'center' })
        
        Args:
            x: 元素中心 X 坐标
            y: 元素中心 Y 坐标
            block: 垂直对齐方式 (start/center/end/nearest)
            behavior: 滚动行为 (instant/smooth/auto)
        
        Returns:
            是否成功滚动
        """
        logger.debug(f"Scrolling element at ({x}, {y}) into view (block={block}, behavior={behavior})")
        
        try:
            # 执行 JS 代码：获取元素并滚动到视口中心
            result = await self.page.evaluate("""
                (coords) => {
                    const { x, y, block, behavior } = coords;
                    const element = document.elementFromPoint(x, y);
                    
                    if (!element) {
                        return { success: false, reason: 'Element not found at coordinates' };
                    }
                    
                    // 检查元素是否在视口中
                    const rect = element.getBoundingClientRect();
                    const isInViewport = (
                        rect.top >= 0 &&
                        rect.left >= 0 &&
                        rect.bottom <= window.innerHeight &&
                        rect.right <= window.innerWidth
                    );
                    
                    if (isInViewport) {
                        return { success: true, reason: 'Element already in viewport', scrolled: false };
                    }
                    
                    // 滚动元素到视口中心（与 JS 版本完全一致）
                    element.scrollIntoView({ 
                        behavior: behavior,  // 'instant' - 立即滚动，无动画
                        block: block         // 'center' - 垂直居中
                    });
                    
                    return { success: true, reason: 'Element scrolled into view', scrolled: true };
                }
            """, {"x": x, "y": y, "block": block, "behavior": behavior})
            
            if result.get('scrolled'):
                logger.info(f"Element scrolled into view: {result.get('reason')}")
                # 等待滚动完成
                await asyncio.sleep(0.3)
            else:
                logger.debug(f"No scroll needed: {result.get('reason')}")
            
            return result.get('success', False)
            
        except Exception as e:
            logger.warning(f"Failed to scroll element into view: {e}")
            return False

    async def scroll_element_by_xpath_into_view(
        self,
        xpath: str,
        block: str = 'center',
        behavior: str = 'instant'
    ) -> bool:
        """
        通过 XPath 将元素滚动到视口中（与 JS 版本完全对齐）
        
        对应 JS 版本: getElementInfoByXpath 中的自动滚动逻辑
        
        Args:
            xpath: 元素的 XPath 路径
            block: 垂直对齐方式 (start/center/end/nearest)
            behavior: 滚动行为 (instant/smooth/auto)
        
        Returns:
            是否成功滚动
        """
        logger.debug(f"Scrolling element by XPath into view: {xpath}")
        
        try:
            # 执行 JS 代码：通过 XPath 获取元素并滚动
            result = await self.page.evaluate("""
                (params) => {
                    const { xpath, block, behavior } = params;
                    
                    // 通过 XPath 查找元素
                    const xpathResult = document.evaluate(
                        xpath,
                        document,
                        null,
                        XPathResult.FIRST_ORDERED_NODE_TYPE,
                        null
                    );
                    
                    const element = xpathResult.singleNodeValue;
                    
                    if (!element || !(element instanceof Element)) {
                        return { success: false, reason: 'Element not found or not an Element type' };
                    }
                    
                    // 检查元素是否部分在视口中（与 JS 版本逻辑一致）
                    const rect = element.getBoundingClientRect();
                    const isPartiallyInViewport = (
                        rect.bottom > 0 &&
                        rect.right > 0 &&
                        rect.top < window.innerHeight &&
                        rect.left < window.innerWidth
                    );
                    
                    if (isPartiallyInViewport) {
                        return { success: true, reason: 'Element already partially in viewport', scrolled: false };
                    }
                    
                    // 🔑 关键：滚动到视口中心（与 JS 版本完全一致）
                    element.scrollIntoView({ 
                        behavior: behavior,  // 'instant' - 立即滚动
                        block: block         // 'center' - 垂直居中
                    });
                    
                    return { success: true, reason: 'Element scrolled into view', scrolled: true };
                }
            """, {"xpath": xpath, "block": block, "behavior": behavior})
            
            if result.get('scrolled'):
                logger.info(f"Element scrolled into view by XPath: {result.get('reason')}")
                # 等待滚动完成
                await asyncio.sleep(0.3)
            else:
                logger.debug(f"No scroll needed: {result.get('reason')}")
            
            return result.get('success', False)
            
        except Exception as e:
            logger.warning(f"Failed to scroll element by XPath into view: {e}")
            return False

    async def execute_script(self, script: str) -> Any:
        """
        执行 JavaScript 脚本（别名方法，与 execute_javascript 一致）
        
        Args:
            script: JavaScript 代码
        
        Returns:
            执行结果
        """
        return await self.evaluate_javascript(script)


__all__ = ["WebPage"]
