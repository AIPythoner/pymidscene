"""
Android 基础示例

前置条件:
1. 安装 Android 额外依赖: `pip install pymidscene[android]`
2. 设备开启 USB 调试, 能通过 `adb devices` 看到.
3. 如果需要中文输入, 请在设备上安装 ADBKeyboard.apk 并设为默认 IME:
     adb install ADBKeyboard.apk
     adb shell ime enable com.android.adbkeyboard/.AdbIME
     adb shell ime set com.android.adbkeyboard/.AdbIME
4. 配置 AI 模型环境变量:
     export MIDSCENE_MODEL_NAME=qwen-vl-max
     export MIDSCENE_MODEL_API_KEY=xxx
     export MIDSCENE_MODEL_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
     export MIDSCENE_MODEL_FAMILY=qwen2.5-vl
"""

import asyncio
import os
from dotenv import load_dotenv

from pymidscene.android import agent_from_adb_device

load_dotenv()
async def main() -> None:
    # 自动选择第一个在线设备, 如需指定 serial: agent_from_adb_device(device_id="xxx")
    agent = await agent_from_adb_device()

    try:
        # 启动应用 — 支持 URL / package/activity / 中文友好名 / package 名
        await agent.launch("小红书")  # 会自动解析为 com.xingin.xhs

        # 等待 app 进入首页
        await asyncio.sleep(3)

        # 用自然语言定位并点击搜索框
        await agent.ai_tap("顶部搜索栏")

        # 输入关键字 (非 ASCII 走 ADBKeyboard)
        await agent.ai_input("搜索框", "Python")

        # 按回车
        await agent.key_press("Enter")

        await asyncio.sleep(2)

        # 提取页面数据
        results = await agent.ai_query(
            {
                "titles": "前 5 条笔记的标题, 返回字符串数组",
            }
        )
        print("搜索结果:", results)

        # 系统返回键
        await agent.back()
    finally:
        # 生成 HTML 报告
        report = agent.finish()
        if report:
            print(f"报告已生成: {report}")


if __name__ == "__main__":
    asyncio.run(main())
