"""
AI 模型基类 - 对应 packages/core/src/ai-model/models/

定义 AI 模型的抽象接口。
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from ....shared.types import AIUsageInfo


class BaseAIModel(ABC):
    """AI 模型抽象基类"""

    def __init__(
        self,
        model_name: str,
        api_key: str,
        base_url: Optional[str] = None,
        **kwargs
    ):
        self.model_name = model_name
        self.api_key = api_key
        self.base_url = base_url
        self.config = kwargs

    @abstractmethod
    def call(
        self,
        messages: List[Dict[str, Any]],
        **kwargs
    ) -> Dict[str, Any]:
        """
        调用 AI 模型

        Args:
            messages: 消息列表
            **kwargs: 其他参数

        Returns:
            包含 content 和 usage 的字典
        """
        pass

    @abstractmethod
    def validate_config(self) -> bool:
        """验证配置是否有效"""
        pass


__all__ = ["BaseAIModel"]
