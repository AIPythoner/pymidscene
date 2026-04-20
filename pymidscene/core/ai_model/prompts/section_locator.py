"""
Two-stage section locator prompt — ports JS ``prompt/llm-section-locator.ts``.

Dense pages (long lists, tables, multi-card layouts) overwhelm a one-shot
locator. The JS visualizer's workflow first asks the model to find the
*containing section*, crops the screenshot to that bbox, then re-runs the
element locator against the crop. This module ports only the prompt side —
the crop + re-locate loop belongs in the agent.

Output shape:
    {"bbox": [x1, y1, x2, y2], "references_bbox"?: [[...], ...], "error"?: "..."}
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

from .common import get_preferred_language, bbox_description


def system_prompt_to_locate_section(model_family: Optional[str] = None) -> str:
    """System prompt instructing the model to bbox the section containing a target."""
    lang = get_preferred_language()
    bbox_fmt = bbox_description(model_family)
    return f"""
## Role:
You are an AI assistant that helps identify UI elements.

## Objective:
- Find a section containing the target element
- If the description mentions reference elements, also locate sections containing those references

## Output Format:
```json
{{
  "bbox": [number, number, number, number],
  "references_bbox"?: [
    [number, number, number, number]
  ],
  "error"?: string
}}
```

Fields:
* `bbox` - Bounding box of the section containing the target element. {bbox_fmt}
* `references_bbox` - Optional array of bounding boxes for reference elements
* `error` - Optional error message if the section cannot be found. Use {lang}.

Example:
If the description is "delete button on the second row with title 'Peter'", return:
```json
{{
  "bbox": [100, 100, 200, 200],
  "references_bbox": [[100, 100, 200, 200]]
}}
```
"""


def section_locator_instruction(section_description: str) -> str:
    """User-turn prompt to pair with the system prompt."""
    return f"Find section containing: {section_description}"


_CODE_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```")


def parse_section_locator_response(content: str) -> Dict[str, Any]:
    """
    Extract ``{bbox, references_bbox, error}`` from a model response.

    Tolerates markdown-fenced and raw JSON. Returns
    ``{"bbox": None, "error": "..."}`` on parse failure so callers can decide
    whether to fall back to the direct locator.
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
        return {"bbox": None, "references_bbox": None, "error": "no JSON object"}
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError as exc:
        return {"bbox": None, "references_bbox": None, "error": f"JSON parse: {exc}"}
    return {
        "bbox": data.get("bbox"),
        "references_bbox": data.get("references_bbox"),
        "error": data.get("error"),
    }


__all__ = [
    "system_prompt_to_locate_section",
    "section_locator_instruction",
    "parse_section_locator_response",
]
