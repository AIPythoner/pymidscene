"""
auto-glm action transformer — ports JS ``auto-glm/actions.ts``.

Takes a ParsedAction (from ``parser.py``) plus screen size and returns a list
of pymidscene-internal PlanningAction dicts that the agent's
``_execute_planned_action`` dispatcher can consume.

Coordinate system contract:
Model outputs are in ``[0, AUTO_GLM_COORDINATE_MAX]`` (default 999); the web
viewport uses CSS pixels. We scale linearly and place a small padding-bbox
around the target so the locate record in cache/report has a rectangle.

Non-web actions (Launch, Home) are emitted as Unsupported stubs with a clear
thought; the dispatcher logs a warning instead of crashing the plan.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple


AUTO_GLM_COORDINATE_MAX = 999
_POINT_BBOX_SIZE = 10


def _auto_glm_to_pixel(
    x: int,
    y: int,
    width: float,
    height: float,
) -> Tuple[float, float]:
    """Scale auto-glm [0, 999] coords to CSS pixel coords."""
    return (
        x * width / AUTO_GLM_COORDINATE_MAX,
        y * height / AUTO_GLM_COORDINATE_MAX,
    )


def _bbox_around(
    cx: float,
    cy: float,
    width: float,
    height: float,
) -> Tuple[int, int, int, int]:
    half = _POINT_BBOX_SIZE / 2
    return (
        int(round(max(cx - half, 0))),
        int(round(max(cy - half, 0))),
        int(round(min(cx + half, width))),
        int(round(min(cy + half, height))),
    )


def _locate_for_point(
    x: int,
    y: int,
    width: float,
    height: float,
    thought: str,
) -> Dict[str, Any]:
    cx, cy = _auto_glm_to_pixel(x, y, width, height)
    return {
        "prompt": thought,
        "bbox": _bbox_around(cx, cy, width, height),
        "center": [cx, cy],
    }


def _swipe_to_scroll(
    start: List[int],
    end: List[int],
    width: float,
    height: float,
) -> Dict[str, Any]:
    """
    Classify a Swipe by dominant axis and convert to a Scroll action.

    Drag direction semantics on touch: finger moves from start → end, so the
    CONTENT moves in the opposite direction. But both JS and this port expose
    the geometric drag direction (start→end) as the `direction` field and
    let the web layer invert if needed; web `scroll()` takes a direction and
    a distance, where `direction=down` scrolls CONTENT up (= finger moves up).
    We match the JS convention here.
    """
    dx = (end[0] - start[0]) * width / AUTO_GLM_COORDINATE_MAX
    dy = (end[1] - start[1]) * height / AUTO_GLM_COORDINATE_MAX
    if abs(dx) > abs(dy):
        direction = "right" if dx > 0 else "left"
        distance = int(abs(dx))
    else:
        direction = "down" if dy > 0 else "up"
        distance = int(abs(dy))
    return {
        "direction": direction,
        "distance": max(distance, 50),
        "scrollType": "singleAction",
    }


def transform_auto_glm_action(
    parsed: Dict[str, Any],
    size: Dict[str, float],
) -> List[Dict[str, Any]]:
    """
    Transform one ParsedAction dict into a list of PlanningAction dicts.

    Returns an empty list for unsupported actions (caller logs/skips) rather
    than raising — JS's equivalent throws, but in a web context we prefer the
    plan to continue past a no-op Launch than to abort.
    """
    width = float(size.get("width") or 0) or 1.0
    height = float(size.get("height") or 0) or 1.0
    metadata = parsed.get("_metadata")
    think = parsed.get("think", "") or ""

    if metadata == "finish":
        return [{
            "type": "Finished",
            "param": {"content": parsed.get("message", "")},
            "thought": think,
        }]

    if metadata != "do":
        return []

    action = parsed.get("action")

    if action == "Tap":
        elem = parsed.get("element") or [0, 0]
        return [{
            "type": "Tap",
            "param": {"locate": _locate_for_point(elem[0], elem[1], width, height, think)},
            "thought": think,
        }]

    if action == "Double Tap":
        elem = parsed.get("element") or [0, 0]
        return [{
            "type": "DoubleClick",
            "param": {"locate": _locate_for_point(elem[0], elem[1], width, height, think)},
            "thought": think,
        }]

    if action == "Long Press":
        # Web has no native long-press; approximate as mouse-down hold via
        # DragAndDrop of zero length (dispatcher falls back to normal click +
        # warning if drag_and_drop missing).
        elem = parsed.get("element") or [0, 0]
        loc = _locate_for_point(elem[0], elem[1], width, height, think)
        return [{
            "type": "Tap",
            "param": {"locate": loc},
            "thought": f"[LongPress→Tap] {think}",
        }]

    if action == "Swipe":
        return [{
            "type": "Scroll",
            "param": _swipe_to_scroll(
                parsed.get("start") or [0, 0],
                parsed.get("end") or [0, 0],
                width,
                height,
            ),
            "thought": think,
        }]

    if action == "Type":
        return [{
            "type": "Input",
            "param": {"value": parsed.get("text", "")},
            "thought": think,
        }]

    if action == "Back":
        # Best-effort on web: history.back() via evaluate_javascript.
        return [{
            "type": "EvaluateJavaScript",
            "param": {"script": "window.history.back();"},
            "thought": think,
        }]

    if action == "Home":
        # Not applicable on web; emit a Sleep so the plan doesn't explode.
        return [{
            "type": "Sleep",
            "param": {"timeMs": 100},
            "thought": f"[Home unsupported on web] {think}",
        }]

    if action == "Launch":
        return [{
            "type": "Sleep",
            "param": {"timeMs": 100},
            "thought": f"[Launch({parsed.get('app')}) unsupported on web] {think}",
        }]

    if action == "Wait":
        return [{
            "type": "Sleep",
            "param": {"timeMs": int(parsed.get("durationMs") or 1000)},
            "thought": think,
        }]

    # Interact / Call_API / Take_over / Note — explicitly unsupported per JS prompt rule #0.
    return []


__all__ = ["transform_auto_glm_action", "AUTO_GLM_COORDINATE_MAX"]
