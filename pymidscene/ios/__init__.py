"""
pymidscene.ios - iOS 自动化支持

通过 WebDriverAgent (WDA) HTTP API 控制 iOS 设备 / 模拟器.

前置条件: 本模块**不负责启动 WDA**. 需要自行启动:

- macOS + Xcode: 通过 Xcode 运行 WebDriverAgent test target, 默认监听 8100
- 真机: `tidevice xctest -B com.facebook.WebDriverAgentRunner.xctrunner`
- 模拟器: `xcodebuild -project WebDriverAgent.xcodeproj -scheme WebDriverAgentRunner ...`

WDA 启动后本库直接走 HTTP, 任意支持 WebDriverAgent HTTP 协议的后端
(包括远程 iOS 设备) 都能接入.

快速上手::

    import asyncio
    from pymidscene.ios import agent_from_webdriver_agent

    async def main():
        agent = await agent_from_webdriver_agent()
        await agent.launch("微信")  # 中文名会解析为 com.tencent.xin
        await agent.ai_tap("扫一扫")
        agent.finish()

    asyncio.run(main())
"""

from .app_name_mapping import DEFAULT_APP_NAME_MAPPING, resolve_bundle_id
from .device import IOSDevice, IOSDeviceOpt
from .agent import IOSAgent
from .utils import agent_from_webdriver_agent, check_ios_environment, is_macos
from .webdriver_client import IOSWebDriverClient

__all__ = [
    "IOSAgent",
    "IOSDevice",
    "IOSDeviceOpt",
    "IOSWebDriverClient",
    "agent_from_webdriver_agent",
    "check_ios_environment",
    "is_macos",
    "DEFAULT_APP_NAME_MAPPING",
    "resolve_bundle_id",
]
