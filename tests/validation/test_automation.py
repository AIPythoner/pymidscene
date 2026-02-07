"""
完整自动化测试 - 验证输入、点击、Hover 等操作
通过 JS 事件监听确保 100% 成功
"""

import asyncio
import os
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


@dataclass
class TestResult:
    name: str
    passed: bool
    expected: str
    actual: str
    error: Optional[str] = None


class AutomationTestRunner:
    """自动化测试运行器"""
    
    def __init__(self, page, agent):
        self.page = page
        self.agent = agent
        self.results: List[TestResult] = []
    
    async def reset(self):
        """重置测试状态"""
        await self.page.evaluate("window.testAPI.reset()")
        await asyncio.sleep(0.3)
    
    async def verify_input(self, element_id: str, expected_value: str) -> bool:
        """验证输入框的值"""
        actual = await self.page.evaluate(f"window.testAPI.getInputValue('{element_id}')")
        return actual == expected_value, actual
    
    async def verify_click(self, test_name: str) -> bool:
        """验证点击是否触发"""
        return await self.page.evaluate(f"window.testAPI.wasClicked('{test_name}')")
    
    async def verify_hover(self, element_id: str) -> bool:
        """验证 hover 是否触发"""
        return await self.page.evaluate(f"window.testAPI.wasHovered('{element_id}')")
    
    async def verify_checkbox(self, element_id: str) -> bool:
        """验证复选框状态"""
        return await self.page.evaluate(f"window.testAPI.isChecked('{element_id}')")
    
    async def verify_radio(self, expected_value: str) -> bool:
        """验证单选框选中值"""
        actual = await self.page.evaluate("window.testAPI.getRadioValue()")
        return actual == expected_value, actual
    
    async def verify_select(self, expected_value: str) -> bool:
        """验证下拉菜单值"""
        actual = await self.page.evaluate("window.testAPI.getSelectValue()")
        return actual == expected_value, actual
    
    async def verify_click_count(self, expected: int) -> bool:
        """验证点击计数"""
        actual = await self.page.evaluate("window.testAPI.getClickCount()")
        return actual == expected, actual
    
    def record(self, name: str, passed: bool, expected: str, actual: str, error: str = None):
        """记录测试结果"""
        self.results.append(TestResult(name, passed, expected, actual, error))
        status = "PASS" if passed else "FAIL"
        print(f"   [{status}] {name}: 期望={expected}, 实际={actual}")
    
    async def test_input(self, description: str, element_id: str, text: str) -> bool:
        """测试输入操作"""
        print(f"\n>> 测试输入: {description}")
        
        try:
            # 执行 AI 输入
            success = await self.agent.ai_input(description, text)
            if not success:
                self.record(f"输入-{element_id}", False, text, "AI定位失败", "ai_input返回False")
                return False
            
            await asyncio.sleep(0.3)
            
            # 验证输入值
            passed, actual = await self.verify_input(element_id, text)
            self.record(f"输入-{element_id}", passed, text, actual or "(空)")
            return passed
            
        except Exception as e:
            self.record(f"输入-{element_id}", False, text, str(e), str(e))
            return False
    
    async def test_click(self, description: str, element_id: str) -> bool:
        """测试点击操作"""
        print(f"\n>> 测试点击: {description}")
        
        try:
            # 执行 AI 点击
            success = await self.agent.ai_click(description)
            if not success:
                self.record(f"点击-{element_id}", False, "clicked", "AI定位失败", "ai_click返回False")
                return False
            
            await asyncio.sleep(0.3)
            
            # 验证点击事件
            test_name = f"点击-{element_id}"
            passed = await self.verify_click(test_name)
            self.record(test_name, passed, "clicked", "clicked" if passed else "not clicked")
            return passed
            
        except Exception as e:
            self.record(f"点击-{element_id}", False, "clicked", str(e), str(e))
            return False
    
    async def test_hover(self, description: str, element_id: str) -> bool:
        """测试 Hover 操作"""
        print(f"\n>> 测试 Hover: {description}")
        
        try:
            # 先定位元素
            result = await self.agent.ai_locate(description)
            if not result:
                self.record(f"Hover-{element_id}", False, "hovered", "AI定位失败")
                return False
            
            # 执行 hover
            x, y = result.center
            await self.agent.interface.hover(x, y)
            await asyncio.sleep(0.3)
            
            # 验证 hover 事件
            passed = await self.verify_hover(element_id)
            self.record(f"Hover-{element_id}", passed, "hovered", "hovered" if passed else "not hovered")
            return passed
            
        except Exception as e:
            self.record(f"Hover-{element_id}", False, "hovered", str(e), str(e))
            return False
    
    async def test_checkbox(self, description: str, element_id: str) -> bool:
        """测试复选框"""
        print(f"\n>> 测试复选框: {description}")
        
        try:
            success = await self.agent.ai_click(description)
            if not success:
                self.record(f"复选框-{element_id}", False, "checked", "AI定位失败")
                return False
            
            await asyncio.sleep(0.3)
            
            passed = await self.verify_checkbox(element_id)
            self.record(f"复选框-{element_id}", passed, "checked", "checked" if passed else "unchecked")
            return passed
            
        except Exception as e:
            self.record(f"复选框-{element_id}", False, "checked", str(e), str(e))
            return False
    
    def print_summary(self):
        """打印测试汇总"""
        print("\n" + "=" * 60)
        print("测试结果汇总")
        print("=" * 60)
        
        passed = sum(1 for r in self.results if r.passed)
        failed = len(self.results) - passed
        
        for r in self.results:
            status = "PASS" if r.passed else "FAIL"
            print(f"  [{status}] {r.name}")
            if not r.passed and r.error:
                print(f"         错误: {r.error}")
        
        print("-" * 60)
        print(f"总计: {len(self.results)} | 通过: {passed} | 失败: {failed}")
        print(f"通过率: {passed/len(self.results)*100:.1f}%" if self.results else "无测试")
        print("=" * 60)
        
        return passed, failed


async def run_automation_tests():
    """运行完整自动化测试"""
    print("=" * 60)
    print("PyMidscene 自动化功能测试")
    print("=" * 60)
    
    from playwright.async_api import async_playwright
    from pymidscene import PlaywrightAgent
    from dotenv import load_dotenv
    
    # 加载环境变量
    load_dotenv()
    
    # 检查配置
    if not os.getenv("MIDSCENE_MODEL_API_KEY"):
        print("❌ 请先配置环境变量！参考 .env.example")
        return 0, 1
    
    test_page = Path(__file__).parent / "test_automation.html"
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, channel="chrome")
        page = await browser.new_page(viewport={"width": 1280, "height": 900})
        
        # 加载测试页面
        print("\n1. 加载测试页面...")
        await page.goto(f"file://{test_page.absolute()}")
        await asyncio.sleep(1)
        await page.screenshot(path='1.png')
        # 创建 Agent
        agent = PlaywrightAgent(page, enable_recording=False)
        
        # 创建测试运行器
        runner = AutomationTestRunner(page, agent)
        
        # ==================== 输入测试 ====================
        print("\n" + "=" * 60)
        print("2. 输入测试")
        print("=" * 60)
        
        await runner.test_input("用户名输入框", "username", "testuser123")
        await runner.test_input("密码输入框", "password", "mypassword")
        await runner.test_input("搜索框", "search-input", "PyMidscene自动化测试")
        
        # ==================== 点击测试 ====================
        print("\n" + "=" * 60)
        print("3. 点击测试")
        print("=" * 60)
        
        await runner.test_click("搜索按钮", "search-btn")
        await runner.test_click("主要按钮", "btn-primary")
        await runner.test_click("危险按钮", "btn-danger")
        await runner.test_click("成功按钮", "btn-success")
        
        # 测试点击计数器
        print("\n>> 测试点击计数器")
        await runner.agent.ai_click("点击+1按钮")
        await asyncio.sleep(0.2)
        await runner.agent.ai_click("点击+1按钮")
        await asyncio.sleep(0.2)
        await runner.agent.ai_click("点击+1按钮")
        await asyncio.sleep(0.3)
        
        passed, actual = await runner.verify_click_count(3)
        runner.record("点击计数器", passed, "3", str(actual))
        
        # ==================== Hover 测试 ====================
        print("\n" + "=" * 60)
        print("4. Hover 测试")
        print("=" * 60)
        
        await runner.test_hover("鼠标悬停区域1", "hover-area-1")
        await runner.test_hover("鼠标悬停区域2", "hover-area-2")
        
        # ==================== 复选框测试 ====================
        print("\n" + "=" * 60)
        print("5. 复选框测试")
        print("=" * 60)

        await page.screenshot(path='2.png')
        await runner.test_checkbox("选项1复选框", "checkbox-1")
        await runner.test_checkbox("选项2复选框", "checkbox-2")
        
        # ==================== 链接测试 ====================
        print("\n" + "=" * 60)
        print("6. 链接测试")
        print("=" * 60)
        
        await runner.test_click("链接1", "link-1")
        await runner.test_click("链接2", "link-2")
        
        # ==================== 汇总 ====================
        passed, failed = runner.print_summary()
        
        # 等待观察
        print("\n>> 测试完成，10秒后关闭浏览器...")
        await asyncio.sleep(10)
        
        await browser.close()
        
        return passed, failed


if __name__ == "__main__":
    passed, failed = asyncio.run(run_automation_tests())
    sys.exit(0 if failed == 0 else 1)
