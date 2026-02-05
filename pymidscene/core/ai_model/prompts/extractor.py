"""
数据提取 Prompt - 对应 packages/core/src/ai-model/prompt/extraction.ts

提供用于 AI 数据提取的 Prompt 模板。
"""

from typing import Any, Dict, List, Optional
import json
from .common import get_preferred_language


def system_prompt_to_extract() -> str:
    """
    生成数据提取的系统 Prompt

    Returns:
        系统 Prompt 字符串
    """
    preferred_language = get_preferred_language()

    return f"""
You are a versatile professional in software UI design and testing. Your outstanding contributions will impact the user experience of billions of users.

The user will give you a screenshot, the contents of it (optional), and some data requirements in <DATA_DEMAND>. You need to understand the user's requirements and extract the data satisfying the <DATA_DEMAND>.

If a key specifies a JSON data type (such as Number, String, Boolean, Object, Array), ensure the returned value strictly matches that data type.

If the user provides multiple reference images, please carefully review the reference images with the screenshot and provide the correct answer for <DATA_DEMAND>.


Return in the following XML format:
<thought>the thinking process of the extraction, less than 300 words. Use {preferred_language} in this field.</thought>
<data-json>the extracted data as JSON. Make sure both the value and scheme meet the DATA_DEMAND. If you want to write some description in this field, use the same language as the DATA_DEMAND.</data-json>
<errors>optional error messages as JSON array, e.g., ["error1", "error2"]</errors>

# Example 1
For example, if the DATA_DEMAND is:

<DATA_DEMAND>
{{
  "name": "name shows on the left panel, string",
  "age": "age shows on the right panel, number",
  "isAdmin": "if the user is admin, boolean"
}}
</DATA_DEMAND>

By viewing the screenshot and page contents, you can extract the following data:

<thought>According to the screenshot, i can see ...</thought>
<data-json>
{{
  "name": "John Doe",
  "age": 30,
  "isAdmin": true
}}
</data-json>
<errors>[]</errors>

# Example 2
If some data is not found in the screenshot, you should return:

<thought>I can see the name and age, but cannot determine if the user is admin...</thought>
<data-json>
{{
  "name": "John Doe",
  "age": 30,
  "isAdmin": null
}}
</data-json>
<errors>["Cannot determine if user is admin from the screenshot"]</errors>
"""


def extract_data_prompt(data_demand: Dict[str, str] | str) -> str:
    """
    生成数据提取的用户 Prompt

    Args:
        data_demand: 数据需求（字典或字符串）

    Returns:
        用户 Prompt 字符串
    """
    if isinstance(data_demand, dict):
        demand_str = json.dumps(data_demand, indent=2, ensure_ascii=False)
    else:
        demand_str = data_demand

    return f"""
<DATA_DEMAND>
{demand_str}
</DATA_DEMAND>

Please extract the data according to the requirements above.
"""


def parse_xml_extraction_response(xml_string: str) -> Dict[str, Any]:
    """
    解析 XML 格式的提取响应

    Args:
        xml_string: XML 响应字符串

    Returns:
        包含 thought, data, errors 的字典
    """
    import re

    def extract_xml_tag(xml: str, tag: str) -> Optional[str]:
        """提取 XML 标签内容"""
        pattern = f"<{tag}>(.*?)</{tag}>"
        match = re.search(pattern, xml, re.DOTALL)
        return match.group(1).strip() if match else None

    thought = extract_xml_tag(xml_string, "thought")
    data_json_str = extract_xml_tag(xml_string, "data-json")
    errors_str = extract_xml_tag(xml_string, "errors")

    # 解析 data-json（必需）
    if not data_json_str:
        raise ValueError("Missing required field: data-json")

    try:
        data = json.loads(data_json_str)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse data-json: {e}")

    # 解析 errors（可选）
    errors: Optional[List[str]] = None
    if errors_str:
        try:
            parsed_errors = json.loads(errors_str)
            if isinstance(parsed_errors, list):
                errors = parsed_errors
        except json.JSONDecodeError:
            pass  # 忽略解析失败

    result = {"data": data}
    if thought:
        result["thought"] = thought
    if errors and len(errors) > 0:
        result["errors"] = errors

    return result


__all__ = [
    "system_prompt_to_extract",
    "extract_data_prompt",
    "parse_xml_extraction_response",
]
