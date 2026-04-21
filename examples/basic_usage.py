"""
基础使用示例 - Basic Usage Example

展示如何使用 PyMidscene 进行 AI 自动化。
Demonstrates how to use PyMidscene for AI automation.

使用前请先配置环境变量，参考 .env.example 文件：
Before running, configure environment variables, see .env.example:

    cp .env.example .env
    # Edit .env with your API key
"""

import asyncio
import os
from dotenv import load_dotenv
from playwright.async_api import async_playwright
from pymidscene import PlaywrightAgent

# 加载 .env 文件中的环境变量
load_dotenv()


async def main():
    """基础示例：百度搜索自动化"""
    
    # 检查环境变量是否配置
    if not os.getenv("MIDSCENE_MODEL_API_KEY"):
        print("❌ 请先配置环境变量！")
        print("   1. 复制 .env.example 为 .env")
        print("   2. 填入你的 API Key")
        return

    async with async_playwright() as p:
        # 启动浏览器
        browser = await p.chromium.launch(headless=False, channel='chrome')
        page = await browser.new_page()

        # 创建 Agent
        agent = PlaywrightAgent(page, cache_id="basic_demo")

        # 访问百度
        await page.goto("https://www.baidu.com")
        await asyncio.sleep(1)

        # 使用自然语言进行自动化操作
        await agent.ai_click("搜索输入框")
        await agent.ai_input("搜索框", "PyMidscene AI 自动化")
        await agent.ai_click("百度一下按钮")
        
        await asyncio.sleep(2)

        # 提取数据
        result = await agent.ai_query({
            "title": "页面标题",
            "has_results": "是否显示搜索结果，布尔值"
        })
        print(f"查询结果: {result.get('data')}")

        # 断言验证
        await agent.ai_assert("页面显示了搜索结果")
        print("✅ 断言通过")

        # 生成报告
        report_path = agent.finish()
        print(f"📄 报告已生成: {report_path}")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
