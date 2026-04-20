"""
auto-glm planner/parser subsystem.

Ports JS ``packages/core/src/ai-model/auto-glm/`` (Zhipu AI's Open-AutoGLM
planning grammar). The parser handles ``<think>...</think><answer>...</answer>``
structured responses, and the grammar emits ``do(action=...)`` / ``finish(...)``
single-line action calls.

Note on porting scope: JS auto-glm targets Android device actions
(Launch/Back/Home/Long Press). pymidscene surfaces this on Playwright web, so
device-specific actions become best-effort (Back → history.back, others warn).
"""

from .parser import (
    parse_auto_glm_response,
    parse_action,
    parse_auto_glm_locate_response,
    extract_value_after,
)
from .planning import parse_auto_glm_planning, is_auto_glm
from .prompt import (
    get_auto_glm_plan_prompt,
    get_auto_glm_locate_prompt,
)
from .actions import transform_auto_glm_action

__all__ = [
    "parse_auto_glm_response",
    "parse_action",
    "parse_auto_glm_locate_response",
    "extract_value_after",
    "parse_auto_glm_planning",
    "is_auto_glm",
    "get_auto_glm_plan_prompt",
    "get_auto_glm_locate_prompt",
    "transform_auto_glm_action",
]
