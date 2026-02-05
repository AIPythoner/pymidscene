"""
任务规划 Prompt - 对应 packages/core/src/ai-model/prompt/llm-planning.ts

提供用于 AI 任务规划的 Prompt 模板（简化版）。
"""

from typing import List, Dict, Any
from .common import get_preferred_language


def system_prompt_to_plan() -> str:
    """
    生成任务规划的系统 Prompt

    Returns:
        系统 Prompt 字符串
    """
    preferred_language = get_preferred_language()

    return f"""
You are an AI assistant that helps automate UI interactions by planning a sequence of actions.

## Objective:
- Analyze the screenshot and user's task description
- Break down the task into a sequence of atomic actions
- Return a YAML-formatted action plan

## Available Actions:
- Tap: Click on an element (requires element description)
- Input: Type text into an input field (requires element description and text)
- Hover: Hover over an element (requires element description)
- KeyPress: Press a keyboard key (requires key name)
- Scroll: Scroll the page (requires direction)
- Sleep: Wait for a specified time (requires time in milliseconds)
- Assert: Verify a condition (requires assertion description)

## Output Format:
Return a YAML list of actions. Each action should have:
- type: action type (Tap, Input, Hover, etc.)
- param: action parameters
- thought: brief explanation of why this action is needed

Example:
```yaml
- type: Tap
  param:
    prompt: "search input box"
  thought: "Locate and click the search box to focus it"

- type: Input
  param:
    prompt: "search input box"
    value: "Python tutorial"
  thought: "Enter the search query"

- type: Tap
  param:
    prompt: "search button"
  thought: "Click search button to submit"
```

Important:
- Use {preferred_language} for thought field
- Keep actions atomic and sequential
- Be specific in element descriptions
"""


def plan_task_prompt(task_description: str) -> str:
    """
    生成任务规划的用户 Prompt

    Args:
        task_description: 任务描述

    Returns:
        用户 Prompt 字符串
    """
    return f"""
Task: {task_description}

Please analyze the screenshot and create a step-by-step action plan to complete this task.
"""


def parse_yaml_plan(yaml_string: str) -> List[Dict[str, Any]]:
    """
    解析 YAML 格式的任务规划

    Args:
        yaml_string: YAML 字符串

    Returns:
        动作列表
    """
    import yaml

    try:
        # 提取 YAML 代码块
        if "```yaml" in yaml_string:
            start = yaml_string.find("```yaml") + 7
            end = yaml_string.find("```", start)
            yaml_string = yaml_string[start:end].strip()
        elif "```" in yaml_string:
            start = yaml_string.find("```") + 3
            end = yaml_string.find("```", start)
            yaml_string = yaml_string[start:end].strip()

        # 解析 YAML
        actions = yaml.safe_load(yaml_string)

        if not isinstance(actions, list):
            raise ValueError("Plan must be a list of actions")

        return actions

    except Exception as e:
        raise ValueError(f"Failed to parse YAML plan: {e}")


__all__ = [
    "system_prompt_to_plan",
    "plan_task_prompt",
    "parse_yaml_plan",
]
