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

from ....shared.utils import js_round


# 对齐 JS auto-glm/actions.ts:10 (AUTO_GLM_COORDINATE_MAX=1000) 与
# common.ts normalized01000 (除以字面量 1000). 用 999 会让每个坐标/距离
# 放大 1000/999 ≈ 1.001 倍.
AUTO_GLM_COORDINATE_MAX = 1000
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
    think: str,
) -> Dict[str, Any]:
    """
    Classify a Swipe by dominant axis and convert to a Scroll param.

    Exactly mirrors JS auto-glm/actions.ts:230-288:
    - delta is computed in the 0-1000 grid; the dominant axis is chosen by
      ``absDeltaY > absDeltaX`` (vertical wins ties-to-vertical).
    - ``direction`` is the direction the page CONTENT moves:
      finger moves down (deltaY>0) => content reveals above => 'up'
      finger moves up   (deltaY<0) => content reveals below => 'down'
      (and left/right symmetrically). The OLD port had both axes inverted.
    - distance = round(abs(delta) * size / 1000); NO 50px floor (the floor made
      short swipes over-scroll up to 2.5x).
    - a ``locate`` is attached from the swipe START so the scroll originates at
      the swiped element/inner container, not the whole viewport.
    """
    delta_x = end[0] - start[0]
    delta_y = end[1] - start[1]
    abs_dx = abs(delta_x)
    abs_dy = abs(delta_y)

    if abs_dy > abs_dx:
        distance = js_round(abs_dy * height / AUTO_GLM_COORDINATE_MAX)
        direction = "up" if delta_y > 0 else "down"
    else:
        distance = js_round(abs_dx * width / AUTO_GLM_COORDINATE_MAX)
        direction = "left" if delta_x > 0 else "right"

    return {
        "locate": _locate_for_point(start[0], start[1], width, height, think),
        "direction": direction,
        "distance": distance,
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
        # JS auto-glm finish puts the completion MESSAGE in `thought` with an
        # empty param. We keep param.content too (the executor's Finished
        # handler logs it), but use the message as the thought to match JS.
        message = parsed.get("message", "")
        return [{
            "type": "Finished",
            "param": {"content": message},
            "thought": message or think,
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
        # 透传为 LongPress: 执行器路由到 interface.long_press
        # (Android/iOS/Playwright 均有实现). 长按与点按在移动端是
        # 完全不同的交互, 不能降级成 Tap.
        elem = parsed.get("element") or [0, 0]
        loc = _locate_for_point(elem[0], elem[1], width, height, think)
        return [{
            "type": "LongPress",
            "param": {"locate": loc},
            "thought": think,
        }]

    if action == "Swipe":
        return [{
            "type": "Scroll",
            "param": _swipe_to_scroll(
                parsed.get("start") or [0, 0],
                parsed.get("end") or [0, 0],
                width,
                height,
                think,
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
        # auto-glm is Android-oriented (JS -> AndroidBackButton). Emit a
        # device-agnostic Back: the executor routes it to interface.back()
        # (Android) / go_back() and falls back to history.back() on web.
        return [{
            "type": "Back",
            "param": {},
            "thought": think,
        }]

    if action == "Home":
        # JS -> AndroidHomeButton. Emit a Home action; the executor routes it
        # to interface.home() (Android/iOS) and no-ops on web.
        return [{
            "type": "Home",
            "param": {},
            "thought": think,
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
