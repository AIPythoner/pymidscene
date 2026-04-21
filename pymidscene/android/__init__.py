"""
pymidscene.android - Android 自动化支持

通过 adb (`adbutils`) 控制 Android 设备, 与 Web 端共享同一套 AI 能力.

安装:
    pip install pymidscene[android]

快速上手::

    import asyncio
    from pymidscene.android import agent_from_adb_device

    async def main():
        agent = await agent_from_adb_device()
        await agent.launch("小红书")
        await agent.ai_tap("搜索框")
        await agent.ai_input("搜索框", "Python")
        agent.finish()

    asyncio.run(main())

`adbutils` 是可选依赖, 未安装时 import 本模块会抛 ImportError, 但不影响
`pymidscene` 其它部分 (Playwright 等) 的使用.
"""

from .app_name_mapping import DEFAULT_APP_NAME_MAPPING, resolve_package_name
from .device import AndroidDevice, AndroidDeviceOpt
from .agent import AndroidAgent
from .utils import ConnectedDevice, agent_from_adb_device, get_connected_devices

__all__ = [
    "AndroidAgent",
    "AndroidDevice",
    "AndroidDeviceOpt",
    "ConnectedDevice",
    "agent_from_adb_device",
    "get_connected_devices",
    "DEFAULT_APP_NAME_MAPPING",
    "resolve_package_name",
]
