"""
豆包（Doubao）视觉模型适配器

支持豆包 Seed 1.6 和 UI-TARS 模型家族。
火山引擎文档: https://www.volcengine.com/docs/82379/1298454
"""

import os
import re
from typing import List, Dict, Any, Optional, Tuple
from openai import OpenAI

from .base import BaseAIModel
from ....shared.logger import logger


class DoubaoVisionModel(BaseAIModel):
    """
    豆包视觉模型适配器

    支持的模型：
    - doubao-vision (Seed 1.6) - 推荐
    - vlm-ui-tars-doubao-1.5 (UI-TARS 1.5)
    - vlm-ui-tars-doubao (UI-TARS 默认版本)

    环境变量配置：
    - MIDSCENE_DOUBAO_API_KEY: API 密钥
    - MIDSCENE_DOUBAO_BASE_URL: API 基础 URL（默认：https://ark.cn-beijing.volces.com/api/v3）
    - MIDSCENE_DOUBAO_MODEL_NAME: 推理接入点 ID（如 ep-20250122xxx）
    """

    DEFAULT_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"

    SUPPORTED_MODELS = [
        "doubao-vision",
        "vlm-ui-tars-doubao",
        "vlm-ui-tars-doubao-1.5",
    ]

    # 豆包使用 0-1000 归一化坐标系统
    COORDINATE_SCALE = 1000

    def __init__(
        self,
        model_name: str = "doubao-vision",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        endpoint_id: Optional[str] = None,
        **kwargs
    ):
        """
        初始化豆包模型

        Args:
            model_name: 模型名称（doubao-vision 或 vlm-ui-tars-doubao-1.5）
            api_key: API 密钥
            base_url: API 基础 URL
            endpoint_id: 推理接入点 ID（ep-xxx）
            **kwargs: 其他参数（temperature, max_tokens 等）
        """
        if model_name not in self.SUPPORTED_MODELS:
            logger.warning(
                f"Model {model_name} not in supported list: {self.SUPPORTED_MODELS}. "
                f"Will try to use it anyway."
            )

        self.model_name = model_name
        self.endpoint_id = endpoint_id or os.getenv("MIDSCENE_DOUBAO_MODEL_NAME", "")
        self.api_key = api_key or os.getenv("MIDSCENE_DOUBAO_API_KEY", "")
        self.base_url = base_url or os.getenv(
            "MIDSCENE_DOUBAO_BASE_URL",
            self.DEFAULT_BASE_URL
        )
        self.model_kwargs = kwargs

        if not self.api_key:
            raise ValueError(
                "Doubao API key is required. Set MIDSCENE_DOUBAO_API_KEY or pass api_key."
            )

        if not self.endpoint_id:
            raise ValueError(
                "Doubao endpoint ID is required. Set MIDSCENE_DOUBAO_MODEL_NAME or pass endpoint_id."
            )

        # 初始化 OpenAI 客户端（豆包兼容 OpenAI API）
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url
        )

        logger.info(
            f"Doubao model initialized: {model_name}, "
            f"endpoint={self.endpoint_id}"
        )

    @classmethod
    def from_env(
        cls,
        model_name: str = "doubao-vision"
    ) -> 'DoubaoVisionModel':
        """
        从环境变量创建模型实例

        环境变量：
        - MIDSCENE_DOUBAO_API_KEY
        - MIDSCENE_DOUBAO_BASE_URL (可选)
        - MIDSCENE_DOUBAO_MODEL_NAME (推理接入点 ID)

        Args:
            model_name: 模型名称

        Returns:
            DoubaoVisionModel 实例
        """
        return cls(model_name=model_name)

    def call(
        self,
        messages: List[Dict[str, Any]],
        stream: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        """
        调用豆包模型

        Args:
            messages: 消息列表（OpenAI 格式）
            stream: 是否流式输出
            **kwargs: 其他参数

        Returns:
            包含 content 和 usage 的字典
        """
        # 合并参数
        request_params = {
            "model": self.endpoint_id,  # 使用推理接入点 ID
            "messages": messages,
            "stream": stream,
            **self.model_kwargs,
            **kwargs
        }

        # 处理深度思考参数（豆包使用 thinking.type）
        deep_think_value = None
        if "deep_think" in request_params:
            deep_think_value = request_params.pop("deep_think")
        elif "deepThink" in request_params:
            deep_think_value = request_params.pop("deepThink")

        if deep_think_value is not None:
            request_params.setdefault("extra_body", {})
            request_params["extra_body"]["config"] = {
                "thinking": {
                    "type": "enabled" if deep_think_value else "disabled"
                }
            }
            logger.debug(f"Doubao deepThink mapped to thinking.type={request_params['extra_body']['config']['thinking']['type']}")

        logger.debug(f"Calling Doubao model: {self.model_name} (endpoint: {self.endpoint_id})")

        try:
            response = self.client.chat.completions.create(**request_params)

            if stream:
                # 流式响应处理
                return {"stream": response}

            # 提取响应内容
            content = response.choices[0].message.content or ""

            # 预处理豆包 bbox 格式（空格分隔 -> 逗号分隔）
            content = self.preprocess_doubao_bbox_json(content)

            # 提取 usage 信息
            usage = None
            if hasattr(response, 'usage') and response.usage:
                usage = {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                }

            logger.debug(f"Doubao response received: {len(content)} chars")

            return {
                "content": content,
                "usage": usage,
                "raw_response": response
            }

        except Exception as e:
            logger.error(f"Doubao API call failed: {e}")
            raise

    @staticmethod
    def preprocess_doubao_bbox_json(input_str: str) -> str:
        """
        预处理豆包 bbox JSON 格式

        豆包可能返回空格分隔的 bbox 值："940 445 969 490"
        需要转换为逗号分隔："940,445,969,490"

        Args:
            input_str: 原始 JSON 字符串

        Returns:
            处理后的 JSON 字符串
        """
        if 'bbox' not in input_str:
            return input_str

        # 将 bbox 值中的空格替换为逗号
        # 匹配模式：数字 + 空格 + 数字
        while re.search(r'\d+\s+\d+', input_str):
            input_str = re.sub(r'(\d+)\s+(\d+)', r'\1,\2', input_str)

        return input_str

    @staticmethod
    def adapt_doubao_bbox(
        bbox: Any,
        width: int,
        height: int
    ) -> Tuple[int, int, int, int]:
        """
        适配豆包 bbox 格式到标准格式
        
        对应 JS 版本: adaptDoubaoBbox (common.ts:108-192)

        豆包支持多种 bbox 格式：
        1. 字符串："x1 y1 x2 y2" (空格分隔，0-1000 归一化坐标)
        2. 字符串数组：["123 222", "789 100"] 或 ["123,222", "789,100"]
        3. 数组：[x1, y1, x2, y2] (0-1000 归一化坐标)
        4. 数组：[x, y] (中心点坐标，自动创建小矩形)

        Args:
            bbox: bbox 值（字符串或数组）
            width: 图像宽度（像素）
            height: 图像高度（像素）

        Returns:
            标准 bbox: (left, top, right, bottom) 像素坐标
        """
        # 使用统一的工具函数
        from ....shared.utils import adapt_doubao_bbox as _adapt_doubao_bbox
        return _adapt_doubao_bbox(bbox, width, height)

    def get_model_name(self) -> str:
        """获取模型名称"""
        return self.model_name

    def get_model_family(self) -> str:
        """获取模型家族"""
        if "ui-tars" in self.model_name:
            return "vlm-ui-tars-doubao"
        return "doubao-vision"

    def validate_config(self) -> bool:
        """
        验证配置是否有效

        Returns:
            配置是否有效
        """
        if not self.api_key:
            logger.error("Doubao API key is missing")
            return False
        if not self.endpoint_id:
            logger.error("Doubao endpoint ID is missing")
            return False
        return True


__all__ = ["DoubaoVisionModel"]
