"""
Prompt 模板模块

提供 AI 模型的各种 Prompt 模板。
"""

from .locator import system_prompt_to_locate_element, find_element_prompt
from .extractor import system_prompt_to_extract, extract_data_prompt, parse_xml_extraction_response
from .planner import system_prompt_to_plan

__all__ = [
    # Locator prompts
    "system_prompt_to_locate_element",
    "find_element_prompt",
    # Extractor prompts
    "system_prompt_to_extract",
    "extract_data_prompt",
    "parse_xml_extraction_response",
    # Planner prompts
    "system_prompt_to_plan",
]
