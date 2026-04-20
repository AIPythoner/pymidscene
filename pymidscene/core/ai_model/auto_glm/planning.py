"""
auto-glm high-level planning entry — ports JS ``auto-glm/planning.ts`` to the
pymidscene agent shape expected by ``parse_planning_response``-style callers.

`parse_auto_glm_planning(raw_response, size)` consumes a raw model string and
returns ``{actions, shouldContinuePlanning, log, raw_response}`` matching the
same contract that ``ui_tars_planning.parse_ui_tars_planning`` returns, so the
agent's ``ai_act`` loop can dispatch uniformly.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .actions import transform_auto_glm_action
from .parser import parse_action, parse_auto_glm_response


_AUTO_GLM_FAMILIES = frozenset(("auto-glm", "auto-glm-multilingual"))


def is_auto_glm(model_family: Optional[str]) -> bool:
    """Matches JS ``isAutoGLM`` (auto-glm/util.ts:8-10)."""
    return model_family in _AUTO_GLM_FAMILIES


def parse_auto_glm_planning(
    raw_response: str,
    size: Dict[str, float],
) -> Dict[str, Any]:
    """
    One-shot planner: raw model text → agent-dispatchable plan.

    Raises ValueError only if nothing could be parsed (empty plan). A ``finish``
    action flips ``shouldContinuePlanning`` to False. Unsupported web actions
    (Home, Launch, Interact, ...) are emitted as no-op Sleep stubs with a
    clear thought so the report still records them rather than aborting.
    """
    response_parts = parse_auto_glm_response(raw_response)

    try:
        parsed_action = parse_action(response_parts)
    except ValueError as exc:
        raise ValueError(
            f"auto-glm plan parse failed: {exc}\nRaw: {raw_response[:500]}"
        ) from exc

    actions = transform_auto_glm_action(parsed_action, size)
    if not actions:
        raise ValueError(
            f"auto-glm produced no executable actions; parsed={parsed_action!r}"
        )

    should_continue = True
    for act in actions:
        if act.get("type") == "Finished":
            should_continue = False
            break

    log = response_parts.get("think", "") or raw_response[:200]

    return {
        "actions": actions,
        "shouldContinuePlanning": should_continue,
        "log": log,
        "raw_response": raw_response,
    }


__all__ = ["parse_auto_glm_planning", "is_auto_glm"]
