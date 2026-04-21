"""
iOS 基础示例

前置条件:
1. 启动 WebDriverAgent, 默认监听 ``localhost:8100``:
   - Xcode: 在 WebDriverAgent 工程里 Product → Test → WebDriverAgentRunner
   - 真机 (Windows/Linux 亦可) 用 tidevice:
        pip install tidevice
        tidevice xctest -B com.facebook.WebDriverAgentRunner.xctrunner
   - 模拟器: 通过 Xcode 先运行一次 WebDriverAgent target 即可
2. 自定义端口或远端: 设 ``MIDSCENE_WDA_HOST`` / ``MIDSCENE_WDA_PORT``
   (比如跑在远端 macOS 服务器, 本地通过 SSH 端口转发)
3. 配置 AI 模型环境变量:
        export MIDSCENE_MODEL_NAME=qwen-vl-max
        export MIDSCENE_MODEL_API_KEY=xxx
        export MIDSCENE_MODEL_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
        export MIDSCENE_MODEL_FAMILY=qwen2.5-vl
"""

import asyncio

from pymidscene.ios import agent_from_webdriver_agent, check_ios_environment


async def main() -> None:
    # 先探测 WDA 是否可用
    probe = await check_ios_environment()
    if not probe["available"]:
        raise RuntimeError(f"WDA not reachable: {probe['error']}")

    async with await agent_from_webdriver_agent() as agent:
        # 启动应用 - 中文名会解析为 bundle id
        await agent.launch("微信")
        await asyncio.sleep(3)

        # 用自然语言定位
        await agent.ai_tap("底部通讯录按钮")
        await asyncio.sleep(1)

        # 提取当前可见的联系人列表
        result = await agent.ai_query(
            {
                "names": "可见区域内所有联系人姓名, 字符串数组",
            }
        )
        print("通讯录:", result)

        # 系统按键
        await agent.home()
        await asyncio.sleep(0.5)
        await agent.app_switcher()


if __name__ == "__main__":
    asyncio.run(main())
