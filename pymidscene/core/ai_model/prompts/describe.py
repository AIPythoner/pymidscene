"""
Element-describer prompt — ports JS ``prompt/describe.ts``.

Used by the locator-cache pipeline to generate a stable, reusable natural-language
identifier for a visually-highlighted element (the UI drew a red rectangle on
the screenshot before sending). The caller then persists the description as
the cache key so that subsequent "click the <same description>" requests can
hit the XPath stored alongside it.

Output shape:
    {"description": "...", "error"?: "..."}
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict

from .common import get_preferred_language


def element_describer_instruction() -> str:
    """System prompt for the element-describer task."""
    lang = get_preferred_language()
    return f"""
Describe the element in the red rectangle for precise identification. Use {lang}.

CRITICAL REQUIREMENTS:
1. UNIQUENESS: The description must uniquely identify this element on the current page
2. UNIVERSALITY: Use generic, reusable selectors that work across different contexts
3. PRECISION: Be specific enough to distinguish from similar elements

DESCRIPTION STRUCTURE:
1. Element type (button, input, link, div, etc.)
2. Primary identifier (in order of preference):
   - Unique text content: "with text 'Login'"
   - Unique attribute: "with aria-label 'Search'"
   - Unique class/ID: "with class 'primary-button'"
   - Unique position: "in header navigation"
3. Secondary identifiers (if needed for uniqueness):
   - Visual features: "blue background", "with icon"
   - Relative position: "below search bar", "in sidebar"
   - Parent context: "in login form", "in main menu"

GUIDELINES:
- Keep description under 25 words
- Prioritize semantic identifiers over visual ones
- Use consistent terminology across similar elements
- Avoid page-specific or temporary content
- Don't mention the red rectangle or selection box
- Focus on stable, reusable characteristics

EXAMPLES:
- "Login button with text 'Sign In'"
- "Search input with placeholder 'Enter keywords'"
- "Navigation link with text 'Home' in header"
- "Submit button in contact form"
- "Menu icon with aria-label 'Open menu'"

Return JSON:
{{
  "description": "unique element identifier",
  "error"?: "error message if any"
}}"""


_CODE_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```")


def parse_describer_response(content: str) -> Dict[str, Any]:
    """
    Extract the describer's JSON payload.

    Tolerates markdown-fenced output and raw JSON. Returns
    ``{"description": str, "error": Optional[str]}`` with empty description
    on parse failure rather than raising, so the caller can gracefully fall
    back to the raw prompt.
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
        return {"description": "", "error": "no JSON object in response"}
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError as exc:
        return {"description": "", "error": f"JSON parse error: {exc}"}
    return {
        "description": str(data.get("description") or ""),
        "error": data.get("error"),
    }


__all__ = ["element_describer_instruction", "parse_describer_response"]
