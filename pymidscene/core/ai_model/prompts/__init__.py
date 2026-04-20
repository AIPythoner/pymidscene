"""
Prompt 模板模块

提供 AI 模型的各种 Prompt 模板。
"""

from .locator import system_prompt_to_locate_element, find_element_prompt
from .extractor import system_prompt_to_extract, extract_data_prompt, parse_xml_extraction_response
from .planner import system_prompt_to_plan, plan_task_prompt, parse_planning_response
from .describe import element_describer_instruction, parse_describer_response
from .section_locator import (
    system_prompt_to_locate_section,
    section_locator_instruction,
    parse_section_locator_response,
)
from .order_sensitive_judge import (
    system_prompt_to_judge_order_sensitive,
    order_sensitive_judge_prompt,
    parse_order_sensitive_response,
    heuristic_is_order_sensitive,
)

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
    "plan_task_prompt",
    "parse_planning_response",
    # Describer
    "element_describer_instruction",
    "parse_describer_response",
    # Section locator
    "system_prompt_to_locate_section",
    "section_locator_instruction",
    "parse_section_locator_response",
    # Order-sensitive judge
    "system_prompt_to_judge_order_sensitive",
    "order_sensitive_judge_prompt",
    "parse_order_sensitive_response",
    "heuristic_is_order_sensitive",
]
