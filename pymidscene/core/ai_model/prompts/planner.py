"""
任务规划 Prompt - 对应 packages/core/src/ai-model/prompt/llm-planning.ts

提供用于 AI 任务规划的 Prompt 模板。
与 JS midscene 的 tasks.ts 中 planning loop 对齐。
"""

from typing import List, Dict, Any, Optional
from .common import get_preferred_language


def system_prompt_to_plan() -> str:
    """
    生成任务规划的系统 Prompt（与 JS 版本完全对齐）

    对应 JS: packages/core/src/ai-model/prompt/llm-planning.ts

    Returns:
        系统 Prompt 字符串
    """
    preferred_language = get_preferred_language()

    return f"""You are an AI assistant that helps automate UI interactions by planning a sequence of actions.
You will receive a screenshot of the current page state and a task description.

## Objective:
- Analyze the screenshot and the user's task description
- Determine what actions are needed to accomplish the task
- If the target element is not visible in the current screenshot, plan a Scroll action first
- Return a JSON response with your planned actions

## Available Actions:
1. **Tap** - Click on an element
   - param: {{ "prompt": "element description" }}
   
2. **Input** - Type text into an input field
   - param: {{ "prompt": "element description", "value": "text to type" }}
   
3. **Hover** - Hover over an element
   - param: {{ "prompt": "element description" }}
   
4. **KeyboardPress** - Press a keyboard key
   - param: {{ "keyName": "Enter" }}
   
5. **Scroll** - Scroll the page (use this when the target element might be outside the visible area)
   - param: {{ "direction": "down"|"up"|"left"|"right", "distance": 500, "scrollType": "singleAction" }}
   - scrollType options: "singleAction" (single scroll), "scrollToBottom", "scrollToTop"
   
6. **Sleep** - Wait for a specified time
   - param: {{ "timeMs": 1000 }}

## Output Format:
Return a JSON object with this structure:
```json
{{
  "actions": [
    {{
      "type": "ActionType",
      "param": {{ ... }},
      "thought": "brief explanation"
    }}
  ],
  "shouldContinuePlanning": false
}}
```

## Rules:
- **IMPORTANT**: If the target element described in the task is NOT visible in the current screenshot, 
  you MUST plan a Scroll action (usually direction "down") FIRST, and set "shouldContinuePlanning" to true.
  This will allow the system to take a new screenshot after scrolling and re-plan.
- Set "shouldContinuePlanning" to true if more actions are needed after the current batch.
- Set "shouldContinuePlanning" to false when the task can be completed with the current actions.
- Keep each action atomic - one action per step.
- Be specific in element descriptions.
- Use {preferred_language} for the "thought" field.
- Plan at most 3 actions per response. If the task needs more steps, set "shouldContinuePlanning" to true.
"""


def plan_task_prompt(
    task_description: str,
    conversation_history: Optional[List[str]] = None
) -> str:
    """
    生成任务规划的用户 Prompt

    Args:
        task_description: 任务描述
        conversation_history: 之前的执行反馈（用于 replan）

    Returns:
        用户 Prompt 字符串
    """
    prompt = f"Task: {task_description}\n\n"

    if conversation_history:
        prompt += "## Previous execution context:\n"
        for item in conversation_history:
            prompt += f"- {item}\n"
        prompt += "\nBased on the current screenshot and the execution history above, plan the next actions.\n"
    else:
        prompt += "Please analyze the screenshot and plan the actions to complete this task.\n"

    return prompt


def parse_planning_response(response_text: str) -> Dict[str, Any]:
    """
    解析 AI 规划响应（JSON 格式）

    对应 JS 版本中 tasks.ts 的 planResult 解析

    Args:
        response_text: AI 返回的文本

    Returns:
        包含 actions 和 shouldContinuePlanning 的字典
    """
    from ....shared.utils import safe_parse_json, extract_json_from_code_block

    # 提取 JSON
    json_text = extract_json_from_code_block(response_text)
    result = safe_parse_json(json_text)

    if not result:
        # 尝试直接解析
        result = safe_parse_json(response_text)

    if not result:
        raise ValueError(f"Failed to parse planning response: {response_text[:200]}")

    # 标准化结果
    actions = result.get("actions", [])
    should_continue = result.get("shouldContinuePlanning", False)

    # 验证 actions 格式
    validated_actions = []
    for action in actions:
        if not isinstance(action, dict):
            continue
        action_type = action.get("type", "")
        param = action.get("param", {})
        thought = action.get("thought", "")
        validated_actions.append({
            "type": action_type,
            "param": param,
            "thought": thought,
        })

    return {
        "actions": validated_actions,
        "shouldContinuePlanning": should_continue,
    }


def parse_yaml_plan(yaml_string: str) -> List[Dict[str, Any]]:
    """
    解析 YAML 格式的任务规划（保留向后兼容）

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
    "parse_planning_response",
    "parse_yaml_plan",
]
