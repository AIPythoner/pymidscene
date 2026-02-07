"""
Prompt 通用工具 - 对应 packages/core/src/ai-model/prompt/common.ts

提供 Prompt 生成的通用函数。
"""

from typing import Optional, Literal


ModelFamily = Optional[Literal[
    "qwen2.5-vl",
    "qwen3-vl",
    "gemini",
    "doubao-vision",
    "vlm-ui-tars",
    "vlm-ui-tars-doubao",
    "vlm-ui-tars-doubao-1.5",
    "glm-v",
    "auto-glm",
    "auto-glm-multilingual",
]]


def bbox_description(model_family: ModelFamily = None) -> str:
    """
    根据模型类型返回 bbox 的描述
    
    对应 JS 版本: bboxDescription (prompt/common.ts:2-7)

    不同模型使用不同的坐标系统：
    - Gemini: [ymin, xmin, ymax, xmax] 归一化到 0-1000
    - 其他模型: [xmin, ymin, xmax, ymax]

    Args:
        model_family: 模型系列

    Returns:
        bbox 格式描述
    """
    if model_family == "gemini":
        return "box_2d bounding box for the target element, should be [ymin, xmin, ymax, xmax] normalized to 0-1000."

    # 默认格式（与 JS 版本对齐）
    return "2d bounding box as [xmin, ymin, xmax, ymax]"


def get_preferred_language() -> str:
    """
    获取首选语言

    Returns:
        首选语言（默认为中文）
    """
    import os
    return os.getenv("MIDSCENE_PREFERRED_LANGUAGE", "Chinese")


__all__ = ["bbox_description", "get_preferred_language", "ModelFamily"]
