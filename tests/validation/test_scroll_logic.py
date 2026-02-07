"""
测试滚动逻辑 - 不使用 AI，直接测试滚动和居中功能
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from playwright.async_api import async_playwright


async def test_scroll_logic():
    """测试滚动逻辑"""
    print("=" * 60)
    print("测试滚动和居中逻辑")
    print("=" * 60)
    
    test_page = Path(__file__).parent / "test_automation.html"
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, channel="chrome")
        page = await browser.new_page(viewport={"width": 1280, "height": 900})
        
        # 加载测试页面
        print("\n1. 加载测试页面...")
        await page.goto(f"file://{test_page.absolute()}")
        await asyncio.sleep(1)
        
        # 测试1：获取页面底部元素的坐标（复选框）
        print("\n2. 测试获取页面底部元素的坐标...")
        checkbox_info = await page.evaluate("""
            () => {
                const checkbox = document.querySelector('#checkbox-1');
                if (!checkbox) return null;
                
                const rect = checkbox.getBoundingClientRect();
                return {
                    top: rect.top,
                    left: rect.left,
                    bottom: rect.bottom,
                    right: rect.right,
                    centerX: rect.left + rect.width / 2,
                    centerY: rect.top + rect.height / 2,
                    inViewport: rect.bottom > 0 && rect.top < window.innerHeight
                };
            }
        """)
        
        if checkbox_info:
            print(f"   复选框位置: top={checkbox_info['top']:.0f}, centerY={checkbox_info['centerY']:.0f}")
            print(f"   视口高度: 900px")
            print(f"   是否在视口中: {checkbox_info['inViewport']}")
        else:
            print("   ❌ 找不到复选框元素")
            await browser.close()
            return
        
        # 测试2：使用 JavaScript 的 scrollIntoView（与我们实现的逻辑一致）
        print("\n3. 测试 JavaScript scrollIntoView (block='center')...")
        await page.evaluate("""
            () => {
                const checkbox = document.querySelector('#checkbox-1');
                if (checkbox) {
                    console.log('Before scroll:', checkbox.getBoundingClientRect().top);
                    checkbox.scrollIntoView({ behavior: 'instant', block: 'center' });
                    console.log('After scroll:', checkbox.getBoundingClientRect().top);
                }
            }
        """)
        await asyncio.sleep(1)
        
        # 检查滚动后的位置
        checkbox_info_after = await page.evaluate("""
            () => {
                const checkbox = document.querySelector('#checkbox-1');
                if (!checkbox) return null;
                
                const rect = checkbox.getBoundingClientRect();
                return {
                    top: rect.top,
                    centerY: rect.top + rect.height / 2,
                    windowHeight: window.innerHeight,
                    expectedCenter: window.innerHeight / 2
                };
            }
        """)
        
        if checkbox_info_after:
            print(f"   滚动后位置: centerY={checkbox_info_after['centerY']:.0f}")
            print(f"   视口中心: {checkbox_info_after['expectedCenter']:.0f}")
            print(f"   是否居中: {abs(checkbox_info_after['centerY'] - checkbox_info_after['expectedCenter']) < 50}")
        
        # 测试3：使用 Playwright 的 locator.click() - 它会自动滚动
        print("\n4. 测试 Playwright locator.click() 的自动滚动...")
        await page.evaluate("window.scrollTo(0, 0)")  # 先滚回顶部
        await asyncio.sleep(1)
        
        print("   滚回顶部...")
        checkbox_before = await page.evaluate("""
            () => {
                const checkbox = document.querySelector('#checkbox-1');
                return checkbox ? checkbox.getBoundingClientRect().top : null;
            }
        """)
        print(f"   复选框位置: top={checkbox_before}")
        
        # 使用 Playwright 的 click - 它会自动滚动
        print("   使用 locator.click()...")
        locator = page.locator('#checkbox-1')
        await locator.click()
        await asyncio.sleep(0.5)
        
        checkbox_clicked = await page.evaluate("window.testAPI.isChecked('checkbox-1')")
        print(f"   点击成功: {checkbox_clicked}")
        
        # 测试4：测试我们的 scroll_element_into_view 方法
        print("\n5. 测试自定义 scroll_element_into_view 方法...")
        from pymidscene.web_integration.playwright import WebPage
        
        web_page = WebPage(page)
        
        # 先滚回顶部
        await page.evaluate("window.scrollTo(0, 0)")
        await asyncio.sleep(1)
        
        # 获取复选框2的中心坐标
        checkbox2_info = await page.evaluate("""
            () => {
                const checkbox = document.querySelector('#checkbox-2');
                if (!checkbox) return null;
                const rect = checkbox.getBoundingClientRect();
                return {
                    centerX: rect.left + rect.width / 2,
                    centerY: rect.top + rect.height / 2,
                    top: rect.top
                };
            }
        """)
        
        print(f"   复选框2位置（滚动前）: top={checkbox2_info['top']:.0f}")
        
        # 调用我们的滚动方法
        success = await web_page.scroll_element_into_view(
            checkbox2_info['centerX'],
            checkbox2_info['centerY'],
            block='center',
            behavior='instant'
        )
        
        print(f"   滚动方法返回: {success}")
        await asyncio.sleep(1)
        
        # 检查滚动后位置
        checkbox2_after = await page.evaluate("""
            () => {
                const checkbox = document.querySelector('#checkbox-2');
                if (!checkbox) return null;
                const rect = checkbox.getBoundingClientRect();
                return {
                    top: rect.top,
                    centerY: rect.top + rect.height / 2,
                    windowHeight: window.innerHeight
                };
            }
        """)
        
        print(f"   复选框2位置（滚动后）: top={checkbox2_after['top']:.0f}, centerY={checkbox2_after['centerY']:.0f}")
        print(f"   视口中心: {checkbox2_after['windowHeight'] / 2:.0f}")
        
        # 测试5：测试直接使用坐标点击（不滚动）
        print("\n6. 测试直接使用坐标点击（不滚动）...")
        await page.evaluate("window.scrollTo(0, 0)")  # 滚回顶部
        await asyncio.sleep(1)
        
        # 获取底部链接的坐标
        link_info = await page.evaluate("""
            () => {
                const link = document.querySelector('#link-1');
                if (!link) return null;
                const rect = link.getBoundingClientRect();
                return {
                    centerX: rect.left + rect.width / 2,
                    centerY: rect.top + rect.height / 2,
                    top: rect.top,
                    inViewport: rect.top < window.innerHeight
                };
            }
        """)
        
        print(f"   链接位置: top={link_info['top']:.0f}, 在视口中: {link_info['inViewport']}")
        print(f"   尝试直接点击坐标 ({link_info['centerX']:.0f}, {link_info['centerY']:.0f})...")
        
        try:
            # 直接点击坐标（不滚动）
            await page.mouse.click(link_info['centerX'], link_info['centerY'])
            await asyncio.sleep(0.5)
            
            link_clicked = await page.evaluate("window.testAPI.wasClicked('点击-link-1')")
            print(f"   点击成功: {link_clicked} ❌ (预期失败，因为元素在视口外)")
        except Exception as e:
            print(f"   点击失败: {e}")
        
        # 等待观察
        print("\n>> 测试完成，10秒后关闭浏览器...")
        await asyncio.sleep(10)
        
        await browser.close()


if __name__ == "__main__":
    asyncio.run(test_scroll_logic())
