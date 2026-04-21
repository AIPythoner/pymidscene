"""
PyMidscene - Python port of Midscene AI automation framework

简化导入，直接使用:
    from pymidscene import PlaywrightAgent

    agent = PlaywrightAgent(page)
    await agent.ai_click("搜索按钮")
"""

# 核心类 - 直接导出
from pymidscene.web_integration.playwright import PlaywrightAgent, WebPage
from pymidscene.core.agent.agent import Agent

# Android 入口 - 条件导入, adbutils 未装则占位
try:
    from pymidscene.android import (  # noqa: F401
        AndroidAgent,
        AndroidDevice,
        AndroidDeviceOpt,
        agent_from_adb_device,
        get_connected_devices,
    )
    _HAS_ANDROID = True
except ImportError:  # pragma: no cover
    _HAS_ANDROID = False

# iOS 入口 - 只依赖 httpx (已是主依赖), 无条件导入
from pymidscene.ios import (  # noqa: F401
    IOSAgent,
    IOSDevice,
    IOSDeviceOpt,
    IOSWebDriverClient,
    agent_from_webdriver_agent,
    check_ios_environment,
)

# 基础类型
from pymidscene.shared.types import (
    Point,
    Size,
    Rect,
    LocateResultElement,
    CacheConfig,
    CacheStrategy,
)

# 日志
from pymidscene.shared.logger import logger

# 版本信息
__version__ = "0.3.0"
__author__ = "PyMidscene Team"

__all__ = [
    # 核心类（推荐使用）
    "PlaywrightAgent",  # 简化 API，直接传入 page
    "WebPage",          # Playwright 适配器
    "Agent",            # 底层 Agent

    # 版本信息
    "__version__",

    # 工具
    "logger",

    # 基础类型
    "Point",
    "Size",
    "Rect",
    "LocateResultElement",
    "CacheConfig",
    "CacheStrategy",
]

# Android 可选导出 (装了 adbutils 才有)
if _HAS_ANDROID:
    __all__ += [
        "AndroidAgent",
        "AndroidDevice",
        "AndroidDeviceOpt",
        "agent_from_adb_device",
        "get_connected_devices",
    ]

# iOS 入口 (默认带)
__all__ += [
    "IOSAgent",
    "IOSDevice",
    "IOSDeviceOpt",
    "IOSWebDriverClient",
    "agent_from_webdriver_agent",
    "check_ios_environment",
]
