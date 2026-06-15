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

import math
import re
from typing import Any, Dict, List, Tuple

from ...shared.logger import logger
from ...shared.utils import js_round


# --- Constants ---------------------------------------------------------------

# Small padding around the clicked point — matches JS `bboxSize = 10`.
# Produces a 10x10 bbox centered on the click point for cache/report purposes.
_POINT_BBOX_SIZE = 10

# UI-TARS box coordinates are integers on a 0-1000 grid. The JS pipeline runs
# the model output through @ui-tars/action-parser with factor:[1000,1000],
# which divides every box number by 1000 to get a normalized 0-1 value before
# multiplying by screen size. Python must do the same division.
_UI_TARS_COORD_FACTOR = 1000.0

# Hotkey alias map — ports the relevant subset of JS `us-keyboard-layout`
# keyMap / transformHotkeyInput so UI-TARS combos like "ctrl c" / "page down"
# become Playwright/driver-recognised key names ("Control+c", "PageDown").
_UI_TARS_KEY_ALIASES = {
    "ctrl": "Control",
    "control": "Control",
    "cmd": "Meta",
    "command": "Meta",
    "meta": "Meta",
    "win": "Meta",
    "super": "Meta",
    "alt": "Alt",
    "option": "Alt",
    "shift": "Shift",
    "enter": "Enter",
    "return": "Enter",
    "esc": "Escape",
    "escape": "Escape",
    "del": "Delete",
    "delete": "Delete",
    "backspace": "Backspace",
    "tab": "Tab",
    "space": "Space",
    "spacebar": "Space",
    "up": "ArrowUp",
    "down": "ArrowDown",
    "left": "ArrowLeft",
    "right": "ArrowRight",
    "arrowup": "ArrowUp",
    "arrowdown": "ArrowDown",
    "arrowleft": "ArrowLeft",
    "arrowright": "ArrowRight",
    "pageup": "PageUp",
    "pagedown": "PageDown",
    "page up": "PageUp",
    "page down": "PageDown",
    "home": "Home",
    "end": "End",
}


def _normalize_hotkey(key: str) -> str:
    """
    Port of JS `transformHotkeyInput` (us-keyboard-layout): if the whole
    string is a known alias use it directly, else split on spaces and map each
    token, joining with '+'. UI-TARS emits space-separated combos.
    """
    raw = (key or "").strip()
    if not raw:
        return raw
    whole = raw.lower()
    if whole in _UI_TARS_KEY_ALIASES:
        return _UI_TARS_KEY_ALIASES[whole]
    tokens = [t for t in re.split(r"[\s+]+", raw) if t]
    out = []
    for tok in tokens:
        lower = tok.lower()
        if lower in _UI_TARS_KEY_ALIASES:
            out.append(_UI_TARS_KEY_ALIASES[lower])
        elif len(tok) == 1:
            out.append(tok.lower() if len(tokens) > 1 else tok)
        else:
            out.append(tok[0].upper() + tok[1:])
    return "+".join(out)


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
    Decode a UI-TARS start_box/end_box value to pixel (x, y), faithfully
    replicating @ui-tars/action-parser + getPoint:

    1. Strip ``()[]`` brackets and split into numbers.
    2. Divide EVERY number by 1000 (the model emits a 0-1000 grid, never 0-1).
    3. The click point is the FIRST PAIR × screen size — i.e. ``getPoint`` uses
       ``const [x,y] = JSON.parse(startBox)``, the first two normalized values.
       For a real 4-number box that is the top-left corner (JS behaviour); for a
       point or an inline ``<bbox>`` (already collapsed to its center before
       parsing) the first pair IS the intended point.

    NOTE: the old `if 0<=x<=1` heuristic never fired for real input (0-1000
    integers) and silently skipped the /1000, putting clicks off by ~1000x.
    """
    text = (start_box or "").strip()
    if not text:
        raise ValueError("start_box is empty")

    cleaned = re.sub(r"[()\[\]]", "", text)
    raw_tokens = [t for t in re.split(r"[,\s]+", cleaned) if t]
    if len(raw_tokens) < 2:
        raise ValueError(f"start_box must have >=2 numbers, got {text!r}")

    try:
        norm = [float(t) / _UI_TARS_COORD_FACTOR for t in raw_tokens]
    except ValueError as exc:
        raise ValueError(f"unrecognised start_box format: {text!r}") from exc

    return norm[0] * width, norm[1] * height


def _point_to_bbox(
    x: float,
    y: float,
    width: float,
    height: float,
) -> Tuple[int, int, int, int]:
    """10x10 clamped bbox around (x,y). Mirrors JS `pointToBbox` (ui-tars-planning.ts:29-40)."""
    half = _POINT_BBOX_SIZE / 2
    return (
        js_round(max(x - half, 0)),
        js_round(max(y - half, 0)),
        js_round(min(x + half, width)),
        js_round(min(y + half, height)),
    )


# --- Action parser -----------------------------------------------------------

# Single thought per response — JS `Thought: ([\s\S]+?)(?=\s*Action[:：]|$)`.
# Note the FULLWIDTH colon `：` (U+FF1A) is accepted alongside ASCII `:`.
_THOUGHT_RE = re.compile(r"Thought:\s*([\s\S]+?)(?=\s*Action[:：]|$)")

# A single action chunk: `action_name(args...)`.
_FUNC_CALL_RE = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_]*)\((.*)\)$", re.DOTALL)

# key='value' / key="value" — value is everything up to the matching quote.
_KV_RE = re.compile(
    r"([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*"
    r"(?:'((?:\\.|[^'\\])*)'|\"((?:\\.|[^\"\\])*)\")"
)


def _parse_kwargs(args_text: str) -> Dict[str, str]:
    """
    Parse `key='value', key2="value2"` argument list, honoring `\\'` `\\"` `\\n` escapes.

    Values come back with escapes materialised (`\\n` → actual newline).
    """
    out: Dict[str, str] = {}
    for match in _KV_RE.finditer(args_text):
        key = match.group(1)
        raw = match.group(2) if match.group(2) is not None else match.group(3)
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

    Mirrors JS `parseActionVlm` ('bc' mode, @ui-tars/action-parser:86-130):
    - ONE thought (first `Thought:` block) is shared by every action.
    - Everything after the LAST `Action:`/`Action：` token is the action body;
      it is split on blank lines into multiple chunks, EACH parsed as a bare
      `name(args)` call (no per-chunk `Action:` prefix required). So
      ``Action: click(...)\n\nright_single(...)`` yields TWO actions.
    """
    results: List[Dict[str, Any]] = []
    text = (text or "").strip()

    thought_match = _THOUGHT_RE.search(text)
    thought = thought_match.group(1).strip() if thought_match else None

    # Isolate the action body: tail after the LAST Action:/Action：, else whole.
    if "Action:" in text or "Action：" in text:
        action_str = re.split(r"Action[:：]", text)[-1]
    else:
        action_str = text

    # Split into chunks on blank lines, parse each as a bare function call.
    for raw_chunk in re.split(r"\n\s*\n", action_str):
        chunk = raw_chunk.strip()
        if not chunk:
            continue
        call = _FUNC_CALL_RE.match(chunk)
        if not call:
            continue
        action_name = call.group(1).lower()
        kwargs = _parse_kwargs(call.group(2))
        results.append({
            "action_type": action_name,
            "action_inputs": kwargs,
            "thought": thought,
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
                    "param": {"locate": locate},
                    "thought": thought,
                })
            elif atype == "left_double":
                locate = _locate_from_box(inputs["start_box"])
                actions_out.append({
                    "type": "DoubleClick",
                    "param": {"locate": locate},
                    "thought": thought,
                })
            elif atype == "right_single":
                locate = _locate_from_box(inputs["start_box"])
                actions_out.append({
                    "type": "RightClick",
                    "param": {"locate": locate},
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
                # 不放 prompt: UI-TARS type 依赖前一步 click 已聚焦, 直接往
                # 焦点元素输入(对齐 JS param={value})。放了 prompt 会让执行器
                # 把模型的 thought 当元素描述去 ai_locate, 浪费且常失败。
                actions_out.append({
                    "type": "Input",
                    "param": {"value": inputs.get("content", "")},
                    "thought": thought,
                })
            elif atype == "scroll":
                # 不放 prompt: 对齐 JS param={direction}, 滚整个视口。放了
                # prompt 会让执行器对 thought 做一次多余的 ai_locate。
                direction = inputs.get("direction", "down")
                actions_out.append({
                    "type": "Scroll",
                    "param": {
                        "direction": direction,
                        "scrollType": "singleAction",
                    },
                    "thought": thought,
                })
            elif atype == "hotkey":
                key = (inputs.get("key") or "").strip()
                if not key:
                    logger.warning("UI-TARS hotkey action missing key; skipping")
                    continue
                # Map key names through the alias table (ctrl->Control,
                # 'page down'->PageDown) like JS transformHotkeyInput, so the
                # driver recognises them regardless of platform.
                normalised = _normalize_hotkey(key)
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
