"""
AI 模型集成模块

提供统一的 AI 模型调用接口和各种模型的适配器。
"""

from .service_caller import call_ai, ModelConfig
from .models.qwen import QwenVLModel
from .models.doubao import DoubaoVisionModel
from .models.base import BaseAIModel
from .prompts import (
    system_prompt_to_locate_element,
    find_element_prompt,
    system_prompt_to_extract,
    extract_data_prompt,
    parse_xml_extraction_response,
)

__all__ = [
    # Service caller
    "call_ai",
    "ModelConfig",
    # Models
    "QwenVLModel",
    "DoubaoVisionModel",
    "BaseAIModel",
    # Prompts
    "system_prompt_to_locate_element",
    "find_element_prompt",
    "system_prompt_to_extract",
    "extract_data_prompt",
    "parse_xml_extraction_response",
]
