"""
任务规划 Prompt - 对应 packages/core/src/ai-model/prompt/llm-planning.ts

**XML 单动作契约**(对齐 JS 现行 planner):每次只规划 **一个** 动作,模型用
XML 标签返回 ``<thought>/<note>/<log>/<error>/<action-type>/<action-param-json>``,
任务完成时返回 ``<complete-task success="true|false">``。执行器执行该单动作后
重新截图、再规划,循环直到 complete-task。

仅用于 **默认** LLM 规划器(qwen / doubao / openai 兼容等)。UI-TARS、auto-glm
有各自独立的 prompt/parser,不走这里。
"""

from __future__ import annotations

import re
from typing import Any

from ....shared.logger import logger
from .common import get_preferred_language


def extract_xml_tag(xml_string: str, tag_name: str) -> str | None:
    """提取 ``<tag>...</tag>`` 的内层文本(大小写不敏感、非贪婪、trim)。

    对齐 JS ``extractXMLTag``:首个匹配优先,无匹配返回 None。
    """
    match = re.search(
        rf"<{tag_name}>([\s\S]*?)</{tag_name}>", xml_string, re.IGNORECASE
    )
    return match.group(1).strip() if match else None


# 默认规划器用基于自然语言 prompt 的 locate(由执行器内部 ai_locate 解析坐标),
# 不在规划响应里要求 bbox —— 保持现有 ai_locate 解析路径不变。
_ACTION_LIST = """\
- Tap, click on an element
  - type: "Tap"
  - param: { "locate": { "prompt": "description of the target element" } }
- Input, type text into an input box or textarea (clears the existing content first)
  - type: "Input"
  - param: { "locate": { "prompt": "the input element" }, "value": "the text to type" }
- Hover, move the pointer over an element
  - type: "Hover"
  - param: { "locate": { "prompt": "the target element" } }
- RightClick, right-click on an element
  - type: "RightClick"
  - param: { "locate": { "prompt": "the target element" } }
- DoubleClick, double-click on an element
  - type: "DoubleClick"
  - param: { "locate": { "prompt": "the target element" } }
- LongPress, press and hold on an element (mobile context menus, drag handles)
  - type: "LongPress"
  - param: { "locate": { "prompt": "the target element" } }
- KeyboardPress, press a keyboard key or chord (e.g. "Enter", "Control+a")
  - type: "KeyboardPress"
  - param: { "keyName": "Enter" }
- Scroll, scroll the page or a scrollable element (use this when the target is NOT visible yet)
  - type: "Scroll"
  - param: { "direction": "down" | "up" | "left" | "right", "distance": 500, "scrollType": "singleAction" | "scrollToBottom" | "scrollToTop", "locate": { "prompt": "scroll inside this element (optional)" } }
- Sleep, wait for a number of milliseconds
  - type: "Sleep"
  - param: { "timeMs": 1000 }
- Assert, verify a condition about the current screen and state a solid conclusion
  - type: "Assert"
  - param: { "condition": "the statement that must be true" }\
"""


def system_prompt_to_plan() -> str:
    """生成默认规划器的 XML 单动作系统 Prompt(对齐 JS systemPromptToTaskPlanning)。"""
    preferred_language = get_preferred_language()

    log_field_instruction = f"""\
## About the `log` field (preamble message)

The `log` field is a brief preamble message to the user explaining what you're about to do:
- **Use {preferred_language}**
- **Keep it concise**: no more than 1-2 sentences (8-12 words), focused on the immediate next step.
- **Build on prior context**: connect to what's been done so far when this is not the first action.

**Examples:**
- "Click the login button"
- "Scroll to find the 'Yes' button in the popup"
- "Previous action failed to find the button, I will try again"\
"""

    return f"""\
Target: User will give you an instruction, some screenshots and previous logs indicating what has been done. Your task is to accomplish the instruction.

Please tell what the next ONE action is (or null if no action should be done) to accomplish the instruction.

## Rules

- Don't give extra actions or plans beyond the instruction. For example, don't submit a form if the instruction is only to fill it.
- Give just the next ONE action you should do.
- Consider the current screenshot and give the action most likely to accomplish the instruction. If the target is not visible, use a Scroll action to find it first instead of guessing.
- Make sure the previous actions completed successfully before performing the next step.
- If there are error messages reported by previous actions, don't give up — plan a new action to recover. If the error persists more than 3 times, set the `<error>` field to the error message.
- Assertions are also important steps. When the instruction asks to verify something, state a solid conclusion by using the "Assert" action.
- Return the `<complete-task>` tag when the task is completed and no more actions should be done.
- If you output an action, do NOT output complete-task.
- The action-type must be one of the Supported actions below. "complete-task" is NOT a valid action-type.

## Supported actions
{_ACTION_LIST}

{log_field_instruction}

## Return format

Return in XML format with the following structure:
<thought>Think through: What is the user's requirement? What is the current state based on the screenshot? What should the next action be (or error, or complete-task)? Write naturally without numbering.</thought>
<note>CRITICAL: If any information from the current screenshot will be needed in follow-up actions, record it here completely. The current screenshot will NOT be available in subsequent steps, so this note is your only way to preserve essential information (extracted data, element states, content to reference). Leave empty if nothing needs to be carried forward.</note>
<log>a brief preamble to the user</log>
<error>error messages (optional)</error>
<action-type>the type of the action (must be one of the Supported actions), or null if no action</action-type>
<action-param-json>JSON object with the action parameters</action-param-json>
<complete-task success="true|false">Optional: finalize the task when all instructions are done. success="true" with the conclusion/result the user needs, or success="false" with an explanation of what went wrong. When present, do NOT include action-type or action-param-json.</complete-task>

## Example

user: <user_instruction>Search for "midscene" and open the first result</user_instruction>

user: this is the latest screenshot
(image ignored due to size optimization)

assistant: <thought>The instruction is to search for "midscene" and open the first result. The screenshot shows a search box at the top. I should type the query into the search box using the Input action.</thought>
<note></note>
<log>Type "midscene" into the search box</log>
<action-type>Input</action-type>
<action-param-json>
{{
  "locate": {{ "prompt": "the main search input box" }},
  "value": "midscene"
}}
</action-param-json>

user: Time: 2026-01-20 14:38:03 (YYYY-MM-DD HH:mm:ss), I have finished the action previously planned.. The last screenshot is attached. Please going on according to the instruction.
(image ignored due to size optimization)

assistant: <thought>The query has been typed. Now I should submit the search by pressing Enter.</thought>
<note></note>
<log>Press Enter to run the search</log>
<action-type>KeyboardPress</action-type>
<action-param-json>
{{ "keyName": "Enter" }}
</action-param-json>

user: Time: 2026-01-20 14:38:08 (YYYY-MM-DD HH:mm:ss), I have finished the action previously planned.. The last screenshot is attached. Please going on according to the instruction.

assistant: <thought>The search results are shown. The first result has been opened in the latest screenshot, so the task is complete.</thought>
<note></note>
<log>Opened the first result, task complete</log>
<complete-task success="true">Opened the first search result for "midscene".</complete-task>
"""


def plan_task_prompt(
    task_description: str,
    conversation_history: list | None = None,
) -> str:
    """构造默认规划器的用户指令(``<user_instruction>...``)。

    XML 单动作循环用消息历史(含截图 + 模型上一轮的原始 XML)承载上下文,所以这里
    只产出本次指令文本;``conversation_history`` 参数保留向后兼容(不再拼接进文本)。
    """
    return f"<user_instruction>{task_description}</user_instruction>"


def parse_planning_response(
    response_text: str, model_family: str | None = None
) -> dict[str, Any]:
    """解析 XML 单动作规划响应(对齐 JS parseXMLPlanningResponse)。

    Returns dict:
        actions: list[{type, param, thought}]  —— 0 或 1 个动作
        shouldContinuePlanning: bool  —— 仅在出现 complete-task 时为 False
        log/thought/note/error: Optional[str]
        finalizeMessage/finalizeSuccess: complete-task 的消息与成败

    Raises:
        ValueError: 缺少必填的 ``<log>``,或 action-param-json 解析失败。
    """
    thought = extract_xml_tag(response_text, "thought")
    note = extract_xml_tag(response_text, "note")
    log = extract_xml_tag(response_text, "log")
    error = extract_xml_tag(response_text, "error")
    action_type = extract_xml_tag(response_text, "action-type")
    action_param_str = extract_xml_tag(response_text, "action-param-json")

    # complete-task 用自己的正则(要捕获 success 属性)。
    finalize_success: bool | None = None
    finalize_message: str | None = None
    complete_match = re.search(
        r'<complete-task\s+success="(true|false)">([\s\S]*?)</complete-task>',
        response_text,
        re.IGNORECASE,
    )
    if complete_match:
        # 精确比较(对齐 JS `=== 'true'`):正则用 IGNORECASE 匹配,但 success
        # 必须字面是小写 true 才算成功,其它(含 TRUE)视为失败。
        finalize_success = complete_match.group(1) == "true"
        finalize_message = complete_match.group(2).strip() or None

    if not log:
        raise ValueError("Missing required field: log")

    action: dict[str, Any] | None = None
    if action_type and action_type.strip().lower() != "null":
        a_type = action_type.strip()
        param: Any = None
        if action_param_str:
            try:
                param = _parse_action_param(action_param_str, model_family)
            except Exception as exc:  # noqa: BLE001
                raise ValueError(
                    f"Failed to parse action-param-json: {exc}"
                ) from exc
        action = {
            "type": a_type,
            "thought": thought or "",
            "param": param if param is not None else {},
        }

    # 冲突:同时给了 action 和 complete-task —— action 优先,丢弃 complete-task。
    if action is not None and finalize_success is not None:
        logger.warning(
            "Planning response included both an action and complete-task; "
            "ignoring complete-task output."
        )
        finalize_message = None
        finalize_success = None

    actions = [action] if action else []
    should_continue = finalize_success is None

    return {
        "actions": actions,
        "shouldContinuePlanning": should_continue,
        "log": log,
        "thought": thought,
        "note": note,
        "error": error,
        "finalizeMessage": finalize_message,
        "finalizeSuccess": finalize_success,
    }


def _parse_action_param(text: str, model_family: str | None = None) -> Any:
    """解析 ``<action-param-json>`` 内容。

    直接复用已有的 :func:`safe_parse_json_with_repair`(它就是 JS safeParseJson
    的忠实移植:extract -> (x,y) 简写 -> json.loads/normalize -> json_repair
    回退 -> doubao/UI-TARS bbox 预处理 -> raise),不再自己手搓一个更弱的解析。
    """
    from ..service_caller import safe_parse_json_with_repair

    return safe_parse_json_with_repair(text, model_family)


def parse_yaml_plan(yaml_string: str) -> list:
    """解析 YAML 格式的任务规划(保留向后兼容)。"""
    import yaml

    try:
        if "```yaml" in yaml_string:
            start = yaml_string.find("```yaml") + 7
            end = yaml_string.find("```", start)
            yaml_string = yaml_string[start:end].strip()
        elif "```" in yaml_string:
            start = yaml_string.find("```") + 3
            end = yaml_string.find("```", start)
            yaml_string = yaml_string[start:end].strip()

        actions = yaml.safe_load(yaml_string)
        if not isinstance(actions, list):
            raise ValueError("Plan must be a list of actions")
        return actions
    except Exception as e:
        raise ValueError(f"Failed to parse YAML plan: {e}") from e


__all__ = [
    "extract_xml_tag",
    "system_prompt_to_plan",
    "plan_task_prompt",
    "parse_planning_response",
    "parse_yaml_plan",
]
