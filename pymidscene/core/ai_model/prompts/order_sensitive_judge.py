"""
Order-sensitive description judge — ports JS ``prompt/order-sensitive-judge.ts``.

Why this exists: descriptions like "第3行的删除按钮" / "the 2nd input" depend on
DOM order. Caching the XPath for such a description is unsafe — when the list
shifts, the same XPath points to a different logical row. Calling this prompt
first lets the locate-cache layer skip caching for order-sensitive prompts
entirely, preventing silent mis-clicks on dynamic pages.

Output shape: ``{"isOrderSensitive": bool}``
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict


def system_prompt_to_judge_order_sensitive() -> str:
    """System prompt classifying a description as order-sensitive or not."""
    return """
## Role:
You are an AI assistant that analyzes UI element descriptions.

## Objective:
Determine whether a given element description is order-sensitive.

Order-sensitive descriptions contain phrases that specify position or sequence, such as:
- "the first button"
- "the second item"
- "the third row"
- "the last input"
- "the 5th element"

Order-insensitive descriptions do not specify position:
- "login button"
- "search input"
- "submit button"
- "user avatar"

## Output Format:
```json
{
  "isOrderSensitive": boolean
}
```

Return true if the description is order-sensitive, false otherwise.
"""


def order_sensitive_judge_prompt(description: str) -> str:
    """User-turn prompt paired with the system prompt above."""
    return f'Analyze this element description: "{description}"'


_CODE_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```")

# Cheap heuristic fallback when model is unavailable — matches common
# ordinal markers in both English and Chinese.
_ORDINAL_HINTS = (
    "first", "second", "third", "fourth", "fifth", "sixth", "seventh",
    "eighth", "ninth", "tenth", "last",
    "1st", "2nd", "3rd", "4th", "5th", "6th", "7th", "8th", "9th", "10th",
    "第一", "第二", "第三", "第四", "第五", "第六", "第七", "第八", "第九", "第十",
    "最后", "最后一个", "倒数",
)


_ARABIC_ORDINAL_RE = re.compile(r"第\s*\d+\s*(个|行|列|条|项|张|页|号|位|款|步)?")
_EN_ORDINAL_RE = re.compile(r"\b\d+(?:st|nd|rd|th)\b", re.IGNORECASE)


def heuristic_is_order_sensitive(description: str) -> bool:
    """
    Local fallback: regex + keyword ordinal phrase detection.

    Returns True if any common ordinal keyword appears. Deliberately
    conservative — false positives (cache-skip a safe prompt) are cheaper
    than false negatives (cache a stale row selector).
    """
    if not description:
        return False
    if _ARABIC_ORDINAL_RE.search(description):
        return True
    if _EN_ORDINAL_RE.search(description):
        return True
    text = description.lower()
    return any(hint in text for hint in _ORDINAL_HINTS)


def parse_order_sensitive_response(content: str) -> Dict[str, Any]:
    """
    Extract ``{"isOrderSensitive": bool}`` from the model response.

    On parse failure returns ``{"isOrderSensitive": True, "error": ...}`` —
    the conservative default, because a false positive only costs a single
    cache miss, while a false negative costs a wrong click.
    """
    text = (content or "").strip()
    candidate = None
    m = _CODE_BLOCK_RE.search(text)
    if m:
        candidate = m.group(1)
    else:
        brace = re.search(r"\{[\s\S]*\}", text)
        if brace:
            candidate = brace.group(0)
    if not candidate:
        return {"isOrderSensitive": True, "error": "no JSON object"}
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError as exc:
        return {"isOrderSensitive": True, "error": f"JSON parse: {exc}"}
    return {
        "isOrderSensitive": bool(data.get("isOrderSensitive", True)),
        "error": data.get("error"),
    }


__all__ = [
    "system_prompt_to_judge_order_sensitive",
    "order_sensitive_judge_prompt",
    "parse_order_sensitive_response",
    "heuristic_is_order_sensitive",
]
