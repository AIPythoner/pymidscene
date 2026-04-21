"""
WebDriver HTTP 协议支持

对应 ``packages/webdriver/``. 目前主要用作 iOS (WDA) 的基础传输层,
未来 Selenium / Appium 等集成也可以复用此模块.
"""

from .client import WebDriverClient, WebDriverError

__all__ = ["WebDriverClient", "WebDriverError"]
