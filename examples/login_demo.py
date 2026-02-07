"""
登录演示 - Login Demo

展示如何使用 PyMidscene 进行登录自动化测试。
Demonstrates login automation with PyMidscene.

使用前请先配置环境变量，参考 .env.example 文件。
"""

import asyncio
import os
from pathlib import Path
from dotenv import load_dotenv
from playwright.async_api import async_playwright
from pymidscene import PlaywrightAgent

# 加载 .env 文件
load_dotenv()


async def main():
    """登录演示：自动填写表单并登录"""
    
    # 检查环境变量
    if not os.getenv("MIDSCENE_MODEL_API_KEY"):
        print("❌ 请先配置环境变量！参考 .env.example")
        return

    # 获取测试页面路径
    html_path = Path(__file__).parent / "login_demo.html"
    html_url = f"file:///{html_path.as_posix()}"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, channel='chrome')
        page = await browser.new_page()

        # 创建 Agent（启用缓存）
        agent = PlaywrightAgent(page)

        # 访问登录页面
        await page.goto(html_url)
        await asyncio.sleep(1)

        # AI 自动化登录流程
        await agent.ai_input("用户名输入框", "admin")
        await agent.ai_input("密码输入框", "123456")
        await agent.ai_click("登录按钮")
        
        await asyncio.sleep(1)

        # 验证登录成功
        await agent.ai_assert("页面显示登录成功")
        print("✅ 登录成功！")

        # 生成可视化报告
        report_path = agent.finish()
        print(f"📄 报告: {report_path}")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
