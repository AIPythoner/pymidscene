"""
测试 Playwright 集成

注意：这些测试需要 Playwright 浏览器驱动
运行前请执行: playwright install chromium
"""

import pytest
import asyncio
from playwright.async_api import async_playwright


# 检查是否安装了 Playwright
try:
    from pymidscene.web_integration.playwright import WebPage
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


@pytest.fixture
async def browser_context():
    """创建 Playwright 浏览器上下文"""
    if not PLAYWRIGHT_AVAILABLE:
        pytest.skip("Playwright not available")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        yield page

        await context.close()
        await browser.close()


@pytest.mark.asyncio
@pytest.mark.skipif(not PLAYWRIGHT_AVAILABLE, reason="Playwright not installed")
async def test_web_page_initialization(browser_context):
    """测试 WebPage 初始化"""
    page = browser_context
    web_page = WebPage(page)

    assert web_page.page == page
    assert web_page.wait_for_navigation_timeout == 10000
    assert web_page.wait_for_network_idle_timeout == 10000


@pytest.mark.asyncio
@pytest.mark.skipif(not PLAYWRIGHT_AVAILABLE, reason="Playwright not installed")
async def test_get_size(browser_context):
    """测试获取视口尺寸"""
    page = browser_context
    await page.set_viewport_size({"width": 1280, "height": 720})

    web_page = WebPage(page)
    size = await web_page.get_size()

    assert size["width"] == 1280
    assert size["height"] == 720


@pytest.mark.asyncio
@pytest.mark.skipif(not PLAYWRIGHT_AVAILABLE, reason="Playwright not installed")
async def test_screenshot(browser_context):
    """测试截图功能"""
    page = browser_context
    await page.goto("about:blank")

    web_page = WebPage(page)
    screenshot = await web_page.screenshot()

    # 验证 Base64 字符串
    assert isinstance(screenshot, str)
    assert len(screenshot) > 0


@pytest.mark.asyncio
@pytest.mark.skipif(not PLAYWRIGHT_AVAILABLE, reason="Playwright not installed")
async def test_navigate_and_screenshot(browser_context):
    """测试导航和截图"""
    page = browser_context
    web_page = WebPage(page)

    # 访问简单的 HTML 页面
    await page.goto("data:text/html,<h1>Hello World</h1>")

    # 截图
    screenshot = await web_page.screenshot()
    assert len(screenshot) > 100


@pytest.mark.asyncio
@pytest.mark.skipif(not PLAYWRIGHT_AVAILABLE, reason="Playwright not installed")
async def test_evaluate_javascript(browser_context):
    """测试执行 JavaScript"""
    page = browser_context
    await page.goto("data:text/html,<h1>Test</h1>")

    web_page = WebPage(page)

    # 执行 JavaScript
    result = await web_page.evaluate_javascript(
        "() => document.querySelector('h1').textContent"
    )

    assert result == "Test"


@pytest.mark.asyncio
@pytest.mark.skipif(not PLAYWRIGHT_AVAILABLE, reason="Playwright not installed")
async def test_click(browser_context):
    """测试点击功能"""
    page = browser_context

    # 创建一个简单的按钮页面
    html = """
    <html>
        <body>
            <button id="test-btn" style="position: absolute; left: 100px; top: 100px; width: 100px; height: 50px;">
                Click Me
            </button>
            <div id="result"></div>
            <script>
                document.getElementById('test-btn').addEventListener('click', () => {
                    document.getElementById('result').textContent = 'Clicked!';
                });
            </script>
        </body>
    </html>
    """
    await page.goto(f"data:text/html,{html}")

    web_page = WebPage(page)

    # 点击按钮中心位置
    await web_page.click(150, 125)

    # 验证点击效果
    result = await page.evaluate("() => document.getElementById('result').textContent")
    assert result == "Clicked!"


@pytest.mark.asyncio
@pytest.mark.skipif(not PLAYWRIGHT_AVAILABLE, reason="Playwright not installed")
async def test_input_text(browser_context):
    """测试文本输入"""
    page = browser_context

    # 创建输入框页面
    html = """
    <html>
        <body>
            <input id="test-input" style="position: absolute; left: 100px; top: 100px; width: 200px;" />
        </body>
    </html>
    """
    await page.goto(f"data:text/html,{html}")

    web_page = WebPage(page)

    # 点击输入框并输入文本
    await web_page.input_text("Hello World", 200, 110)

    # 验证输入内容
    value = await page.evaluate("() => document.getElementById('test-input').value")
    assert value == "Hello World"


@pytest.mark.asyncio
@pytest.mark.skipif(not PLAYWRIGHT_AVAILABLE, reason="Playwright not installed")
async def test_scroll(browser_context):
    """测试滚动功能"""
    page = browser_context

    # 创建长页面
    html = """
    <html>
        <body style="height: 3000px;">
            <div id="top" style="height: 100px;">Top</div>
        </body>
    </html>
    """
    await page.goto(f"data:text/html,{html}")

    web_page = WebPage(page)

    # 向下滚动
    await web_page.scroll("down", 500)

    # 验证滚动位置
    scroll_y = await page.evaluate("() => window.scrollY")
    assert scroll_y > 0


@pytest.mark.asyncio
@pytest.mark.skipif(not PLAYWRIGHT_AVAILABLE, reason="Playwright not installed")
async def test_key_press(browser_context):
    """测试按键功能"""
    page = browser_context

    # 创建输入框页面
    html = """
    <html>
        <body>
            <input id="test-input" autofocus />
            <div id="result"></div>
            <script>
                document.getElementById('test-input').addEventListener('keydown', (e) => {
                    if (e.key === 'Enter') {
                        document.getElementById('result').textContent = 'Enter pressed!';
                    }
                });
            </script>
        </body>
    </html>
    """
    await page.goto(f"data:text/html,{html}")

    web_page = WebPage(page)

    # 按 Enter 键
    await web_page.key_press("Enter")

    # 验证按键效果
    result = await page.evaluate("() => document.getElementById('result').textContent")
    assert result == "Enter pressed!"


@pytest.mark.asyncio
@pytest.mark.skipif(not PLAYWRIGHT_AVAILABLE, reason="Playwright not installed")
async def test_get_ui_context(browser_context):
    """测试获取 UI 上下文"""
    page = browser_context
    await page.set_viewport_size({"width": 1280, "height": 720})
    await page.goto("data:text/html,<h1>Test Page</h1>")

    web_page = WebPage(page)
    ui_context = await web_page.get_ui_context()

    # 验证上下文
    assert ui_context.screenshot is not None
    assert ui_context.size["width"] == 1280
    assert ui_context.size["height"] == 720
