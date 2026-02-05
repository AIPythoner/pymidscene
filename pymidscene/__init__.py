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
__version__ = "0.1.0"
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
