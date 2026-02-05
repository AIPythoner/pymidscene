"""
元素定位 Prompt - 对应 packages/core/src/ai-model/prompt/llm-locator.ts

提供用于 AI 元素定位的 Prompt 模板。
"""

from .common import bbox_description, get_preferred_language, ModelFamily


def system_prompt_to_locate_element(model_family: ModelFamily = None) -> str:
    """
    生成元素定位的系统 Prompt

    Args:
        model_family: 模型系列

    Returns:
        系统 Prompt 字符串
    """
    preferred_language = get_preferred_language()
    bbox_comment = bbox_description(model_family)

    return f"""
## Role:
You are an AI assistant that helps identify UI elements.

## Objective:
- Identify elements in screenshots that match the user's description.
- Provide the coordinates of the element that matches the user's description.

## Output Format:
```json
{{
  "bbox": [number, number, number, number],  // {bbox_comment}
  "errors"?: string[]
}}
```

Fields:
* `bbox` is the bounding box of the element that matches the user's description
* `errors` is an optional array of error messages (if any)

For example, when an element is found:
```json
{{
  "bbox": [100, 100, 200, 200],
  "errors": []
}}
```

When no element is found:
```json
{{
  "bbox": [],
  "errors": ["I can see ..., but {{some element}} is not found. Use {preferred_language}."]
}}
```
"""


def find_element_prompt(target_element_description: str) -> str:
    """
    生成查找元素的用户 Prompt

    Args:
        target_element_description: 目标元素描述

    Returns:
        用户 Prompt 字符串
    """
    return f"Find: {target_element_description}"


__all__ = [
    "system_prompt_to_locate_element",
    "find_element_prompt",
]
