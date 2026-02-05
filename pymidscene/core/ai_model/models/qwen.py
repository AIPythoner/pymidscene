"""
千问模型适配器 - Qwen VL 模型支持

提供对阿里云千问视觉语言模型的支持。
"""

from typing import Dict, Any, List, Optional
from .base import BaseAIModel
from ..service_caller import ModelConfig, call_ai


class QwenVLModel(BaseAIModel):
    """千问 VL 模型适配器"""

    # 默认配置
    DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    SUPPORTED_MODELS = [
        "qwen-vl-max",
        "qwen-vl-plus",
        "qwen2-vl-7b-instruct",
        "qwen2-vl-72b-instruct",
    ]

    def __init__(
        self,
        model_name: str = "qwen-vl-max",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        **kwargs
    ):
        """
        初始化千问模型

        Args:
            model_name: 模型名称（qwen-vl-max 或 qwen-vl-plus）
            api_key: API 密钥（千问的 API Key）
            base_url: API 基础 URL
            temperature: 温度参数
            max_tokens: 最大 token 数
            **kwargs: 其他参数
        """
        # 如果没有提供 base_url，使用默认值
        if base_url is None:
            base_url = self.DEFAULT_BASE_URL

        super().__init__(
            model_name=model_name,
            api_key=api_key or "",
            base_url=base_url,
            **kwargs
        )

        self.temperature = temperature
        self.max_tokens = max_tokens

        # 验证模型名称
        if model_name not in self.SUPPORTED_MODELS:
            raise ValueError(
                f"Unsupported model: {model_name}. "
                f"Supported models: {', '.join(self.SUPPORTED_MODELS)}"
            )

    def validate_config(self) -> bool:
        """验证配置是否有效"""
        if not self.api_key:
            raise ValueError("API key is required for Qwen VL model")

        if not self.base_url:
            raise ValueError("Base URL is required for Qwen VL model")

        return True

    def call(
        self,
        messages: List[Dict[str, Any]],
        **kwargs
    ) -> Dict[str, Any]:
        """
        调用千问模型

        Args:
            messages: 消息列表（OpenAI 格式）
            **kwargs: 其他参数（如 temperature, max_tokens）

        Returns:
            包含 content 和 usage 的字典
        """
        # 验证配置
        self.validate_config()

        # 创建模型配置
        model_config = ModelConfig(
            model_name=self.model_name,
            base_url=self.base_url,
            api_key=self.api_key,
            temperature=kwargs.get("temperature", self.temperature),
            max_tokens=kwargs.get("max_tokens", self.max_tokens),
            timeout=kwargs.get("timeout", 60000),
            retry_count=kwargs.get("retry_count", 1),
            retry_interval=kwargs.get("retry_interval", 2000),
            http_proxy=kwargs.get("http_proxy"),
            model_description=f"Qwen VL {self.model_name}",
            intent=kwargs.get("intent"),
        )

        # 调用 AI
        result = call_ai(
            messages=messages,
            model_config=model_config,
            stream=kwargs.get("stream", False),
            on_chunk=kwargs.get("on_chunk"),
        )

        return result

    @classmethod
    def from_env(cls, model_name: str = "qwen-vl-max") -> 'QwenVLModel':
        """
        从环境变量创建模型实例

        Args:
            model_name: 模型名称

        Returns:
            QwenVLModel 实例
        """
        import os

        api_key = os.getenv("MIDSCENE_QWEN_API_KEY")
        base_url = os.getenv(
            "MIDSCENE_QWEN_BASE_URL",
            cls.DEFAULT_BASE_URL
        )

        if not api_key:
            raise ValueError(
                "MIDSCENE_QWEN_API_KEY environment variable is required"
            )

        return cls(
            model_name=model_name,
            api_key=api_key,
            base_url=base_url,
        )


__all__ = ["QwenVLModel"]
