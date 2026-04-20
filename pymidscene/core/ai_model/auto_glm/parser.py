"""
auto-glm response parser — ports JS ``auto-glm/parser.ts``.

Grammar:
- Response may be wrapped in ``<think>...</think><answer>...</answer>`` OR
  contain bare ``do(action=...)`` / ``finish(message=...)`` lines.
- Action calls use ``key="value"`` Python-literal-style args. Parser must
  handle ``\\"`` escapes inside content (the JS author's comment explicitly
  warns that regex-only extraction fails on e.g.
  ``finish(message="Now \\\"Tom\\\" is here.")``).

Output: ParsedAction dict keyed by ``_metadata`` (``'do'`` or ``'finish'``) plus
per-action fields.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional


def extract_value_after(src: str, key: str) -> str:
    """
    Return the substring of ``src`` that follows ``key``, trimming the final
    ``")`` if present. Mirrors JS ``extractValueAfter`` (parser.ts:8-18).

    Used for ``text=``, ``message=``, ``app=``, ``instruction=`` etc. — any
    string value where escaped quotes inside the value can break a naive regex.
    """
    idx = src.find(key)
    if idx == -1:
        raise ValueError(f"Missing key {key!r} in action payload: {src!r}")
    rest = src[idx + len(key):].strip()
    if rest.endswith('")'):
        rest = rest[:-2]
    return rest


_ACTION_NAME_RE = re.compile(r'do\(action="([^"]+)"')
_ELEMENT_RE = re.compile(r"element=\[(\d+)\s*,\s*(\d+)\]")
_START_RE = re.compile(r"start=\[(\d+)\s*,\s*(\d+)\]")
_END_RE = re.compile(r"end=\[(\d+)\s*,\s*(\d+)\]")
_DURATION_RE = re.compile(r'duration=(?:["\[])?(\d+)')


def parse_action(response: Dict[str, str]) -> Dict[str, Any]:
    """
    Parse an auto-glm action call into a ParsedAction dict.

    Input: ``{"think": str, "content": str}`` (from ``parse_auto_glm_response``).
    Output: dict with ``_metadata`` and action-specific fields.
    """
    trimmed = (response.get("content") or "").strip()
    think = response.get("think", "")

    try:
        # Type / Type_Name variants share a single output shape.
        if trimmed.startswith('do(action="Type"') or trimmed.startswith(
            'do(action="Type_Name"'
        ):
            text = extract_value_after(trimmed, 'text="')
            return {"_metadata": "do", "action": "Type", "text": text, "think": think}

        # Finish call — top-level, not inside do(...).
        if trimmed.startswith("finish(message="):
            message = extract_value_after(trimmed, 'finish(message="')
            if message.endswith(")"):
                message = message[:-1]
            return {"_metadata": "finish", "message": message, "think": think}

        if not trimmed.startswith("do("):
            raise ValueError(f"Failed to parse action: {trimmed!r}")

        name_match = _ACTION_NAME_RE.search(trimmed)
        if not name_match:
            raise ValueError(
                f"Failed to extract action type from do() call: {trimmed!r}"
            )
        action_type = name_match.group(1)
        base: Dict[str, Any] = {"_metadata": "do", "think": think}

        if action_type == "Tap":
            m = _ELEMENT_RE.search(trimmed)
            if not m:
                raise ValueError(
                    f"Failed to extract element for Tap: {trimmed!r}"
                )
            return {**base, "action": "Tap", "element": [int(m.group(1)), int(m.group(2))]}

        if action_type == "Double Tap":
            m = _ELEMENT_RE.search(trimmed)
            if not m:
                raise ValueError(
                    f"Failed to extract element for Double Tap: {trimmed!r}"
                )
            return {
                **base,
                "action": "Double Tap",
                "element": [int(m.group(1)), int(m.group(2))],
            }

        if action_type == "Swipe":
            s = _START_RE.search(trimmed)
            e = _END_RE.search(trimmed)
            if not s or not e:
                raise ValueError(
                    f"Failed to extract start/end for Swipe: {trimmed!r}"
                )
            return {
                **base,
                "action": "Swipe",
                "start": [int(s.group(1)), int(s.group(2))],
                "end": [int(e.group(1)), int(e.group(2))],
            }

        if action_type == "Long Press":
            m = _ELEMENT_RE.search(trimmed)
            if not m:
                raise ValueError(
                    f"Failed to extract element for Long Press: {trimmed!r}"
                )
            return {
                **base,
                "action": "Long Press",
                "element": [int(m.group(1)), int(m.group(2))],
            }

        if action_type == "Launch":
            app = extract_value_after(trimmed, 'app="')
            return {**base, "action": "Launch", "app": app}

        if action_type == "Back":
            return {**base, "action": "Back"}

        if action_type == "Home":
            return {**base, "action": "Home"}

        if action_type == "Wait":
            m = _DURATION_RE.search(trimmed)
            if not m:
                raise ValueError(
                    f"Failed to extract duration for Wait: {trimmed!r}"
                )
            seconds = int(m.group(1))
            return {**base, "action": "Wait", "durationMs": seconds * 1000}

        if action_type == "Interact":
            return {**base, "action": "Interact"}
        if action_type == "Call_API":
            instruction = extract_value_after(trimmed, 'instruction="')
            return {**base, "action": "Call_API", "instruction": instruction}
        if action_type == "Take_over":
            message = extract_value_after(trimmed, 'message="')
            return {**base, "action": "Take_over", "message": message}
        if action_type == "Note":
            message = extract_value_after(trimmed, 'message="')
            return {**base, "action": "Note", "message": message}

        raise ValueError(f"Unknown action type: {action_type!r}")

    except Exception as exc:
        raise ValueError(
            f"Failed to parse auto-glm action ({exc}); raw={trimmed!r}"
        ) from exc


_THINK_TAG_RE = re.compile(r"</?think>")
_CLOSING_ANSWER_RE = re.compile(r"</answer>")
_THINK_BLOCK_RE = re.compile(r"<think>([\s\S]*?)</think>")
_ANSWER_BLOCK_RE = re.compile(r"<answer>([\s\S]*?)</answer>")


def parse_auto_glm_response(content: str) -> Dict[str, str]:
    """
    Split a raw auto-glm response into ``{think, content}``.

    Ordering rationale (slightly diverges from JS ``parseAutoGLMResponse`` to
    be robust against mixed-shape responses that leaked trailing ``</answer>``
    into value strings in the JS version):

    1. If BOTH ``<answer>`` tags are present, extract the inner blocks first —
       the XML wrapper is the prompt-mandated primary shape, and inner content
       is then parsed as a bare ``do(...)`` / ``finish(...)`` call.
    2. Bare ``finish(message=...)`` / ``do(action=...)`` at top level — for
       models that dropped the XML wrapper.
    3. Only ``<answer>`` without a closing tag — legacy fallback.
    4. Otherwise treat the whole content as the action.
    """
    # Case 1: well-formed <answer>...</answer> — extract inner blocks cleanly
    answer_match = _ANSWER_BLOCK_RE.search(content)
    if answer_match:
        think_match = _THINK_BLOCK_RE.search(content)
        think_text = think_match.group(1).strip() if think_match else ""
        return {"think": think_text, "content": answer_match.group(1).strip()}

    if "finish(message=" in content:
        think, _, rest = content.partition("finish(message=")
        return {"think": think.strip(), "content": f"finish(message={rest}"}
    if "do(action=" in content:
        think, _, rest = content.partition("do(action=")
        return {"think": think.strip(), "content": f"do(action={rest}"}

    if "<answer>" in content:
        think_part, _, answer_part = content.partition("<answer>")
        think = _THINK_TAG_RE.sub("", think_part).strip()
        action = _CLOSING_ANSWER_RE.sub("", answer_part).strip()
        return {"think": think, "content": action}
    return {"think": "", "content": content}


def parse_auto_glm_locate_response(raw_response: str) -> Dict[str, Any]:
    """
    Parse locate-only response. Returns
    ``{think, coordinates: {x,y} | None, error?: str}``.
    Mirrors JS ``parseAutoGLMLocateResponse`` (parser.ts:212-245).
    """
    parsed = parse_auto_glm_response(raw_response)
    action_content = parsed["content"]
    think = parsed["think"]
    if not action_content.startswith('do(action="Tap"'):
        return {
            "think": think,
            "coordinates": None,
            "error": f"Unexpected action type in auto-glm locate response: {action_content!r}",
        }
    m = _ELEMENT_RE.search(action_content)
    if not m:
        return {
            "think": think,
            "coordinates": None,
            "error": f"Failed to extract element from auto-glm response: {action_content!r}",
        }
    return {
        "think": think,
        "coordinates": {"x": int(m.group(1)), "y": int(m.group(2))},
    }


__all__ = [
    "extract_value_after",
    "parse_action",
    "parse_auto_glm_response",
    "parse_auto_glm_locate_response",
]
