"""
UI-TARS planner prompt — ports JS `packages/core/src/ai-model/prompt/ui-tars-planning.ts`.

Why this exists separately from `planner.py`:
UI-TARS models emit a textual `Thought: / Action:` grammar with inline `<bbox>`
tags, not JSON. Using the generic JSON planner prompt against a UI-TARS model
produces unparseable output, which is the audit's C2 bug. This module provides
the prompt and the `get_summary` cleanup routine that strips `Reflection:`
sections before appending to conversation history.
"""

from __future__ import annotations

import re
from typing import Optional

from .common import get_preferred_language


_UI_TARS_PROMPT_TEMPLATE = """
You are a GUI agent. You are given a task and your action history, with screenshots. You need to perform the next action to complete the task.

## Output Format
```
Thought: ...
Action: ...
```

## Action Space

click(start_box='[x1, y1, x2, y2]')
left_double(start_box='[x1, y1, x2, y2]')
right_single(start_box='[x1, y1, x2, y2]')
drag(start_box='[x1, y1, x2, y2]', end_box='[x3, y3, x4, y4]')
hotkey(key='')
type(content='xxx') # Use escape characters \\', \\", and \\n in content part to ensure we can parse the content in normal python string format. If you want to submit your input, use \\n at the end of content.
scroll(start_box='[x1, y1, x2, y2]', direction='down or up or right or left')
wait() #Sleep for 5s and take a screenshot to check for any changes.
finished(content='xxx') # Use escape characters \\', \\", and \\n in content part to ensure we can parse the content in normal python string format.


## Note
- Use {preferred_language} in `Thought` part.
- Write a small plan and finally summarize your next action (with its target element) in one sentence in `Thought` part.

## User Instruction
"""


def get_ui_tars_planning_prompt(preferred_language: Optional[str] = None) -> str:
    """Return the UI-TARS system prompt. Caller appends the user instruction after it."""
    lang = preferred_language or get_preferred_language()
    return _UI_TARS_PROMPT_TEMPLATE.format(preferred_language=lang)


_REFLECTION_RE = re.compile(
    r"Reflection:[\s\S]*?(?=Action_Summary:|Action:|$)"
)


def get_summary(prediction: str) -> str:
    """
    Strip ``Reflection: ...`` blocks before the next ``Action_Summary:`` / ``Action:``
    anchor or end-of-text, so the model's internal self-critique isn't persisted
    into the conversation history where it would poison subsequent planning turns.
    Mirrors JS `getSummary` (prompt/ui-tars-planning.ts:36-39).
    """
    return _REFLECTION_RE.sub("", prediction).strip()


__all__ = ["get_ui_tars_planning_prompt", "get_summary"]
