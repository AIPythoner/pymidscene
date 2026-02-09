"""
小红书视频上传自动化 - XHS Video Upload Demo

使用 PyMidscene 自动化小红书创作者平台的视频上传流程：
1. 打开小红书创作者发布页面
2. 上传视频文件
3. 填写标题
4. 选择自主声明选项
5. 点击发布

使用前请先配置环境变量，参考 .env.example 文件。

与 JS 版本完全对齐：
- 使用 ai_wait_for 替代手动轮询
- 使用 ai_action 替代 ai_click（自动处理滚动）
- 不再需要手动 scroll
"""

import asyncio
import os
import time
from dotenv import load_dotenv
from playwright.async_api import async_playwright
from pymidscene import PlaywrightAgent

# 加载 .env 文件
load_dotenv()


async def main():
    """小红书视频上传自动化流程"""

    # 检查环境变量
    if not os.getenv("MIDSCENE_MODEL_API_KEY"):
        print("请先配置环境变量！参考 .env.example")
        return

    # ============ 配置区 ============
    # 视频文件路径，请根据实际情况修改
    video_path = r"C:\Users\Administrator\Downloads\QQ202616-75856.mp4"
    # 视频标题
    video_title = "你好世界"
    # 小红书创作者发布页面 URL
    publish_url = "https://creator.xiaohongshu.com/publish/publish?from=menu"
    # ================================

    # 浏览器用户数据目录（保留登录态等缓存）
    user_data_dir = r"E:\留档\qinghu_ai_browser_data"

    print(f"视频文件路径: {video_path}")
    print(f"浏览器数据目录: {user_data_dir}")
    start_time = time.time()

    async with async_playwright() as p:
        # 使用持久化上下文启动浏览器，加载已有的缓存和登录态
        context = await p.chromium.launch_persistent_context(
            user_data_dir,
            headless=False,
            channel="chrome",
        )
        # 使用已有页面或新建页面
        page = context.pages[0] if context.pages else await context.new_page()

        # 设置视口大小（与 JS 版本对齐）
        await page.set_viewport_size({"width": 1280, "height": 768})

        # 创建 PlaywrightAgent
        agent = PlaywrightAgent(page, cache_id='xhs')

        # 注册文件选择器事件处理（在点击上传之前注册）
        # 当系统弹出文件选择对话框时，自动选择指定的视频文件
        async def handle_file_chooser(file_chooser):
            print("捕捉到文件上传事件")
            await file_chooser.set_files(video_path)

        page.on("filechooser", handle_file_chooser)

        # 1. 打开小红书创作者发布页面
        await page.goto(publish_url, wait_until="domcontentloaded")
        await asyncio.sleep(3)

        # 2. 等待页面加载完成（与 JS 版本 aiWaitFor 对齐）
        await agent.ai_wait_for("页面显示了笔记管理", timeout=30)
        await agent.ai_assert("页面显示了笔记管理")
        print("页面加载完成")

        # 3. 点击文件上传框（与 JS 版本 aiAction 对齐）
        s_t = time.time()
        await agent.ai_action("点击页面中间的文件上传框")
        e_t = time.time()
        print(f"点击视频上传按钮耗时：{e_t - s_t:.2f}s")

        # 等待视频上传处理
        await asyncio.sleep(10)

        # 4. 填写标题
        await agent.ai_assert("页面出现了标题输入框")
        s_t = time.time()
        await agent.ai_input("标题输入框", video_title)
        e_t = time.time()
        print(f"标题输入耗时：{e_t - s_t:.2f}s")

        # 5. 选择自主声明选项（与 JS 版本完全对齐，不再需要手动 scroll）
        # ai_action 会自动处理元素不在视口中的情况：
        # AI 发现当前截图中看不到目标元素 → 规划 Scroll 动作 → 滚动后重新截图 → 找到元素后操作
        await agent.ai_action("点击自主声明选项的下拉选择框")
        await agent.ai_action("选择自主声明选项 虚拟演绎")

        # 6. 点击发布
        await agent.ai_action("点击发布按钮")

        # 7. 截图保存结果
        await page.screenshot(path="screenshot.png")
        print("截图已保存: screenshot.png")

        await asyncio.sleep(3)

        # 打印总耗时
        total_time = time.time() - start_time
        print(f"总耗时：{total_time:.2f}s")

        # 生成可视化报告
        report_path = agent.finish()
        if report_path:
            print(f"报告: {report_path}")

        await context.close()


if __name__ == "__main__":
    asyncio.run(main())
