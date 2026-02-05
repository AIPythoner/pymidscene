"""
抽象接口定义 - 对应 packages/core/src/device/

定义设备交互的统一接口，支持 Web、Android、iOS 等平台。
"""

from typing import Optional, Dict, Any, List, Protocol
from abc import ABC, abstractmethod

from ..core.types import UIContext
from ..shared.types import Size


class AbstractInterface(ABC):
    """设备交互抽象接口"""

    @abstractmethod
    async def get_ui_context(self) -> UIContext:
        """
        获取当前 UI 上下文（包括截图和尺寸）

        Returns:
            UIContext 实例
        """
        pass

    @abstractmethod
    async def get_size(self) -> Size:
        """
        获取视口尺寸

        Returns:
            Size 字典
        """
        pass

    @abstractmethod
    async def screenshot(self, full_page: bool = False) -> str:
        """
        获取截图（Base64 编码）

        Args:
            full_page: 是否截取完整页面

        Returns:
            Base64 编码的图像字符串
        """
        pass

    @abstractmethod
    async def click(self, x: float, y: float) -> None:
        """
        点击指定坐标

        Args:
            x: X 坐标
            y: Y 坐标
        """
        pass

    @abstractmethod
    async def input_text(self, text: str, x: Optional[float] = None, y: Optional[float] = None) -> None:
        """
        输入文本

        Args:
            text: 要输入的文本
            x: 可选的 X 坐标（先点击再输入）
            y: 可选的 Y 坐标（先点击再输入）
        """
        pass

    @abstractmethod
    async def hover(self, x: float, y: float) -> None:
        """
        悬停到指定坐标

        Args:
            x: X 坐标
            y: Y 坐标
        """
        pass

    @abstractmethod
    async def scroll(self, direction: str, distance: Optional[int] = None) -> None:
        """
        滚动页面

        Args:
            direction: 滚动方向（up/down/left/right）
            distance: 滚动距离（像素）
        """
        pass

    @abstractmethod
    async def key_press(self, key: str) -> None:
        """
        按键

        Args:
            key: 按键名称（Enter、Escape 等）
        """
        pass

    @abstractmethod
    async def wait_for_navigation(self, timeout: Optional[int] = None) -> None:
        """
        等待导航完成

        Args:
            timeout: 超时时间（毫秒）
        """
        pass

    @abstractmethod
    async def wait_for_network_idle(self, timeout: Optional[int] = None) -> None:
        """
        等待网络空闲

        Args:
            timeout: 超时时间（毫秒）
        """
        pass

    @abstractmethod
    async def evaluate_javascript(self, script: str) -> Any:
        """
        执行 JavaScript 代码

        Args:
            script: JavaScript 代码

        Returns:
            执行结果
        """
        pass

    # ==================== XPath 相关方法（与 JS 版本对齐） ====================

    async def get_element_xpath(self, x: float, y: float) -> Optional[str]:
        """
        获取指定坐标处元素的 XPath

        Args:
            x: X 坐标
            y: Y 坐标

        Returns:
            元素的 XPath 路径，如果找不到则返回 None
        """
        # 默认实现，子类可以覆盖
        return None

    async def get_element_by_xpath(self, xpath: str) -> Optional[Dict[str, Any]]:
        """
        通过 XPath 获取元素信息（边界框和中心点）

        Args:
            xpath: 元素的 XPath 路径

        Returns:
            包含 bbox, center, rect 的字典，如果找不到则返回 None
        """
        # 默认实现，子类可以覆盖
        return None


__all__ = ["AbstractInterface"]
