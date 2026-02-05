"""
Playwright 集成模块

提供 Playwright 的 WebPage 适配器和 PlaywrightAgent。
"""

from .page import WebPage
from .agent import PlaywrightAgent

__all__ = [
    "WebPage",
    "PlaywrightAgent",
]
