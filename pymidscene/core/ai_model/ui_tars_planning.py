"""
UI-TARS response parser + planner — ports JS `packages/core/src/ai-model/ui-tars-planning.ts`.

JS uses the `@ui-tars/action-parser` npm package; Python reimplements the grammar
inline here because there's no equivalent package on PyPI. The grammar is:

    Thought: <free text>
    Action: <action_name>(<kwarg1='...', kwarg2='...'>)

Multiple `Action:` lines under a single `Thought:` block are allowed; the thought
attaches to each. Inline `<bbox>x1 y1 x2 y2</bbox>` tokens must be rewritten to
`(cx, cy)` pixel-center strings BEFORE parsing (see `convert_bbox_to_coordinates`).

The start_box / end_box arg is either a JSON-like "[x, y]" normalized pair
(in 0-1 range) or the "(cx,cy)" form produced by the bbox → center rewrite.
`_parse_start_box` handles both.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any, Dict, List, Optional, Tuple

from ...shared.logger import logger


# --- Constants ---------------------------------------------------------------

# Small padding around the clicked point — matches JS `bboxSize = 10`.
# Produces a 10x10 bbox centered on the click point for cache/report purposes.
_POINT_BBOX_SIZE = 10


# --- Text preprocessing ------------------------------------------------------

_BBOX_RE = re.compile(r"<bbox>(\d+)\s+(\d+)\s+(\d+)\s+(\d+)</bbox>")
_EOS_RE = re.compile(r"\[EOS\]")


def convert_bbox_to_coordinates(text: str) -> str:
    """
    Rewrite ``<bbox>x1 y1 x2 y2</bbox>`` tokens to ``(cx,cy)`` and strip ``[EOS]``.

    Mirrors JS `convertBboxToCoordinates` (ui-tars-planning.ts:317-345).
    Center is computed with floor division to match JS `Math.floor`.
    """

    def repl(match: re.Match[str]) -> str:
        x1, y1, x2, y2 = (int(match.group(i)) for i in range(1, 5))
        cx = math.floor((x1 + x2) / 2)
        cy = math.floor((y1 + y2) / 2)
        return f"({cx},{cy})"

    stripped = _EOS_RE.sub("", text)
    return _BBOX_RE.sub(repl, stripped).strip()


# --- Coordinate helpers ------------------------------------------------------

def _parse_start_box(
    start_box: str,
    width: float,
    height: float,
) -> Tuple[float, float]:
    """
    Decode a UI-TARS start_box/end_box value to pixel (x, y).

    Two forms are accepted:
    - JSON "[x, y]" with x,y normalized to 0-1 → multiplied by size.
    - "(cx,cy)" (produced by `convert_bbox_to_coordinates`) → used as-is.

    JSON-style with values > 1 is also tolerated (taken as already-pixel coords).
    """
    text = (start_box or "").strip()
    if not text:
        raise ValueError("start_box is empty")

    # (cx, cy) pixel-center form — output of bbox→center rewrite.
    if text.startswith("(") and text.endswith(")"):
        inner = text[1:-1]
        parts = [p.strip() for p in inner.split(",") if p.strip()]
        if len(parts) >= 2:
            return float(parts[0]), float(parts[1])

    # JSON array "[x, y]" or "[x1, y1, x2, y2]" form.
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"unrecognised start_box format: {text!r}") from exc

    if not isinstance(parsed, list) or len(parsed) < 2:
        raise ValueError(f"start_box must be a list of >=2 numbers, got {parsed!r}")

    # 4-value bbox → take its center
    if len(parsed) >= 4:
        x = (float(parsed[0]) + float(parsed[2])) / 2
        y = (float(parsed[1]) + float(parsed[3])) / 2
    else:
        x = float(parsed[0])
        y = float(parsed[1])

    # Values in 0-1 are normalized; otherwise already pixels.
    if 0 <= x <= 1 and 0 <= y <= 1:
        return x * width, y * height
    return x, y


def _point_to_bbox(
    x: float,
    y: float,
    width: float,
    height: float,
) -> Tuple[int, int, int, int]:
    """10x10 clamped bbox around (x,y). Mirrors JS `pointToBbox` (ui-tars-planning.ts:29-40)."""
    half = _POINT_BBOX_SIZE / 2
    return (
        int(round(max(x - half, 0))),
        int(round(max(y - half, 0))),
        int(round(min(x + half, width))),
        int(round(min(y + half, height))),
    )


# --- Action parser -----------------------------------------------------------

# Matches: `action_name(key1='value1', key2='value2', ...)`
# The value capture handles single-quoted strings with escaped quotes/backslashes;
# JS source explicitly permits `\'`, `\"`, `\n` escapes in type/finished content.
_ACTION_LINE_RE = re.compile(
    r"Action:\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\((.*?)\)\s*(?=(?:\nThought:|\nAction:|$))",
    re.DOTALL,
)

# key='value' — value is everything up to the next unescaped single quote.
_KV_RE = re.compile(
    r"([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*'((?:\\.|[^'\\])*)'"
)


def _parse_kwargs(args_text: str) -> Dict[str, str]:
    """
    Parse `key='value', key2='value2'` argument list, honoring `\\'` `\\"` `\\n` escapes.

    Values come back with escapes materialised (`\\n` → actual newline).
    """
    out: Dict[str, str] = {}
    for match in _KV_RE.finditer(args_text):
        key = match.group(1)
        raw = match.group(2)
        # Materialise \\n / \\' / \\" / \\\\
        value = (
            raw.replace("\\n", "\n")
            .replace("\\'", "'")
            .replace('\\"', '"')
            .replace("\\\\", "\\")
        )
        out[key] = value
    return out


def parse_ui_tars_response(text: str) -> List[Dict[str, Any]]:
    """
    Parse a UI-TARS model response into a list of action dicts.

    Each dict has shape:
        {
            "action_type": str,   # e.g. "click", "drag", "type"
            "action_inputs": {start_box?, end_box?, content?, key?, direction?},
            "thought": Optional[str],
        }

    Supports repeated Action: lines sharing the preceding Thought:. Reflection:
    blocks should already be stripped by `get_summary` before reaching here,
    but we tolerate them gracefully.
    """
    results: List[Dict[str, Any]] = []

    # Split by "Thought:" anchors; first element before any Thought: is scanned
    # for orphan Action: lines (rare but observed in some model outputs).
    sections = re.split(r"(?:^|\n)Thought:", text)

    if sections and sections[0].strip():
        # Orphan Action: lines without a preceding Thought.
        for match in _ACTION_LINE_RE.finditer("\n" + sections[0]):
            action_name = match.group(1).lower()
            kwargs = _parse_kwargs(match.group(2))
            results.append({
                "action_type": action_name,
                "action_inputs": kwargs,
                "thought": None,
            })

    for section in sections[1:]:
        # section now starts with the thought text followed by Action: line(s)
        # Split thought vs. action block at the first "\nAction:" (or end).
        action_match = re.search(r"\nAction:", section)
        if action_match:
            thought = section[: action_match.start()].strip()
            action_block = section[action_match.start():]
        else:
            thought = section.strip()
            action_block = ""

        if not action_block:
            continue

        for match in _ACTION_LINE_RE.finditer(action_block):
            action_name = match.group(1).lower()
            kwargs = _parse_kwargs(match.group(2))
            results.append({
                "action_type": action_name,
                "action_inputs": kwargs,
                "thought": thought or None,
            })

    return results


# --- Planning integration ----------------------------------------------------

def transform_ui_tars_actions(
    parsed: List[Dict[str, Any]],
    size: Dict[str, float],
) -> Tuple[List[Dict[str, Any]], bool, List[str]]:
    """
    Convert parsed UI-TARS actions to pymidscene's internal action format.

    Returns (actions, should_continue_planning, unhandled_types).

    Action shapes match those produced by `planner.py`/`_execute_planned_action`
    so the same agent dispatch works for both JSON-planner and UI-TARS paths.
    Mirrors JS `transformActions` mapping (ui-tars-planning.ts:108-251).
    """
    width = float(size.get("width") or 0) or 1.0
    height = float(size.get("height") or 0) or 1.0

    actions_out: List[Dict[str, Any]] = []
    unhandled: List[str] = []
    should_continue = True

    for entry in parsed:
        atype = (entry.get("action_type") or "").lower()
        inputs: Dict[str, Any] = entry.get("action_inputs") or {}
        thought: str = entry.get("thought") or ""

        def _locate_from_box(box: str) -> Dict[str, Any]:
            px, py = _parse_start_box(box, width, height)
            return {
                "prompt": thought,
                "bbox": _point_to_bbox(px, py, width, height),
                "center": [px, py],
            }

        try:
            if atype == "click":
                locate = _locate_from_box(inputs["start_box"])
                actions_out.append({
                    "type": "Tap",
                    "param": {"locate": locate, "prompt": thought},
                    "thought": thought,
                })
            elif atype == "left_double":
                locate = _locate_from_box(inputs["start_box"])
                actions_out.append({
                    "type": "DoubleClick",
                    "param": {"locate": locate, "prompt": thought},
                    "thought": thought,
                })
            elif atype == "right_single":
                locate = _locate_from_box(inputs["start_box"])
                actions_out.append({
                    "type": "RightClick",
                    "param": {"locate": locate, "prompt": thought},
                    "thought": thought,
                })
            elif atype == "drag":
                from_locate = _locate_from_box(inputs["start_box"])
                to_locate = _locate_from_box(inputs["end_box"])
                actions_out.append({
                    "type": "DragAndDrop",
                    "param": {"from": from_locate, "to": to_locate},
                    "thought": thought,
                })
            elif atype == "type":
                actions_out.append({
                    "type": "Input",
                    "param": {"value": inputs.get("content", ""), "prompt": thought},
                    "thought": thought,
                })
            elif atype == "scroll":
                direction = inputs.get("direction", "down")
                actions_out.append({
                    "type": "Scroll",
                    "param": {
                        "direction": direction,
                        "scrollType": "singleAction",
                        "prompt": thought,
                    },
                    "thought": thought,
                })
            elif atype == "hotkey":
                key = (inputs.get("key") or "").strip()
                if not key:
                    logger.warning("UI-TARS hotkey action missing key; skipping")
                    continue
                # Normalise: UI-TARS uses space-separated key combos in some versions,
                # but the canonical form is `+` — pass through directly.
                normalised = "+".join(part for part in re.split(r"[\s+]+", key) if part)
                actions_out.append({
                    "type": "KeyboardPress",
                    "param": {"keyName": normalised},
                    "thought": thought,
                })
            elif atype == "wait":
                actions_out.append({
                    "type": "Sleep",
                    "param": {"timeMs": 1000},
                    "thought": thought,
                })
            elif atype == "finished":
                should_continue = False
                actions_out.append({
                    "type": "Finished",
                    "param": {"content": inputs.get("content", "")},
                    "thought": thought,
                })
            elif atype:
                unhandled.append(atype)
        except (KeyError, ValueError) as exc:
            logger.warning(f"UI-TARS action {atype} failed to transform: {exc}")
            unhandled.append(atype)

    return actions_out, should_continue, unhandled


def parse_ui_tars_planning(
    raw_response: str,
    size: Dict[str, float],
) -> Dict[str, Any]:
    """
    One-shot entry used by the agent's `ai_act`.

    Takes the raw model string, does bbox-rewrite + parse + transform, and
    returns `{actions, shouldContinuePlanning, log, raw_response}`.

    Raises ValueError when no actions could be extracted (matches JS behaviour).
    """
    converted = convert_bbox_to_coordinates(raw_response)
    parsed = parse_ui_tars_response(converted)
    actions, should_continue, unhandled = transform_ui_tars_actions(parsed, size)

    if not actions:
        details: List[str] = ["UI-TARS returned no executable actions."]
        if not parsed:
            details.append(
                "Parser found no Action: lines "
                "(response may be malformed or missing the Action directive)."
            )
        if unhandled:
            details.append(f"Unhandled action types: {', '.join(unhandled)}")
        details.append(f"Raw response: {raw_response[:500]}")
        raise ValueError("\n".join(details))

    # Import lazily to avoid circular imports — prompt module is small.
    from .prompts.ui_tars_planning import get_summary

    log = get_summary(raw_response)

    return {
        "actions": actions,
        "shouldContinuePlanning": should_continue,
        "log": log,
        "raw_response": raw_response,
        "unhandled": unhandled,
    }


__all__ = [
    "convert_bbox_to_coordinates",
    "parse_ui_tars_response",
    "transform_ui_tars_actions",
    "parse_ui_tars_planning",
]
