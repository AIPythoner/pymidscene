"""
Regression tests for the model/coordinate/prompt/parser fidelity fixes
(round 5 review): UI-TARS coordinate scaling + parsing, auto-glm swipe
semantics, js_round, Doubao string-array handling, max_tokens omission.
"""

from __future__ import annotations

import pytest

from pymidscene.shared.utils import (
    js_round,
    adapt_doubao_bbox,
    format_bbox,
    adapt_bbox_to_rect,
)
from pymidscene.core.ai_model.ui_tars_planning import (
    parse_ui_tars_planning,
    _parse_start_box,
    _normalize_hotkey,
)
from pymidscene.core.ai_model.auto_glm.actions import (
    transform_auto_glm_action,
    AUTO_GLM_COORDINATE_MAX,
)


# --- js_round (Math.round parity) -------------------------------------------

class TestJsRound:
    @pytest.mark.parametrize("value,expected", [
        (4.5, 5),    # python round() -> 4 (banker's); JS Math.round -> 5
        (0.5, 1),    # python round() -> 0
        (2.5, 3),    # python round() -> 2
        (12.5, 13),
        (1.4, 1),
        (1.6, 2),
        (-0.5, 0),   # floor(-0.5 + 0.5) = floor(0.0) = 0
    ])
    def test_round_half_up(self, value, expected):
        assert js_round(value) == expected


# --- UI-TARS coordinate scaling (off-by-1000 fix) ---------------------------

class TestUiTarsCoordinates:
    def test_box_divided_by_1000_and_first_pair(self):
        # [100,200,300,400] on 1280x720: norm first pair (0.1,0.2) * size
        x, y = _parse_start_box("[100, 200, 300, 400]", 1280, 720)
        assert (round(x), round(y)) == (128, 144)

    def test_point_form_is_centerish(self):
        # (500,500) -> norm (0.5,0.5) * size = screen center
        x, y = _parse_start_box("(500,500)", 1000, 2000)
        assert (round(x), round(y)) == (500, 1000)

    def test_two_number_json(self):
        x, y = _parse_start_box("[250, 750]", 1000, 1000)
        assert (round(x), round(y)) == (250, 750)

    def test_click_action_end_to_end(self):
        out = parse_ui_tars_planning(
            "Thought: tap login\nAction: click(start_box='[100,200,300,400]')",
            {"width": 1280, "height": 720},
        )
        assert len(out["actions"]) == 1
        tap = out["actions"][0]
        assert tap["type"] == "Tap"
        cx, cy = tap["param"]["locate"]["center"]
        assert (round(cx), round(cy)) == (128, 144)


# --- UI-TARS multi-action parsing -------------------------------------------

class TestUiTarsParsing:
    def test_multiple_actions_share_one_thought(self):
        # Blank-line-separated, second chunk has NO Action: prefix (JS behaviour)
        out = parse_ui_tars_planning(
            "Thought: do two things\n"
            "Action: click(start_box='(500,500)')\n\n"
            "type(content='hello')",
            {"width": 1000, "height": 1000},
        )
        types = [a["type"] for a in out["actions"]]
        assert types == ["Tap", "Input"]
        assert out["actions"][1]["param"]["value"] == "hello"

    def test_fullwidth_colon_action(self):
        # Fullwidth colon U+FF1A after Action
        out = parse_ui_tars_planning(
            "Thought: t\nAction： click(start_box='(100,100)')",
            {"width": 1000, "height": 1000},
        )
        assert len(out["actions"]) == 1
        assert out["actions"][0]["type"] == "Tap"

    def test_finished_stops_planning(self):
        out = parse_ui_tars_planning(
            "Thought: done\nAction: finished(content='all good')",
            {"width": 800, "height": 600},
        )
        assert out["shouldContinuePlanning"] is False

    def test_type_param_has_no_prompt_key(self):
        # `prompt:thought` would make the executor ai_locate on the reasoning
        # text instead of typing into the focused element.
        out = parse_ui_tars_planning(
            "Thought: type my query\nAction: type(content='hello world')",
            {"width": 800, "height": 600},
        )
        param = out["actions"][0]["param"]
        assert param == {"value": "hello world"}
        assert "prompt" not in param

    def test_scroll_param_has_no_prompt_key(self):
        out = parse_ui_tars_planning(
            "Thought: scroll to find it\nAction: scroll(direction='down')",
            {"width": 800, "height": 600},
        )
        param = out["actions"][0]["param"]
        assert "prompt" not in param
        assert param["direction"] == "down"

    def test_click_param_has_no_top_level_prompt(self):
        out = parse_ui_tars_planning(
            "Thought: tap it\nAction: click(start_box='(500,500)')",
            {"width": 800, "height": 600},
        )
        param = out["actions"][0]["param"]
        assert "prompt" not in param  # the element is in locate.center
        assert "center" in param["locate"]


# --- UI-TARS hotkey normalization -------------------------------------------

class TestUiTarsHotkey:
    @pytest.mark.parametrize("raw,expected", [
        ("ctrl c", "Control+c"),
        ("ctrl+a", "Control+a"),
        ("enter", "Enter"),
        ("page down", "PageDown"),
        ("meta v", "Meta+v"),
    ])
    def test_normalize(self, raw, expected):
        assert _normalize_hotkey(raw) == expected

    def test_hotkey_action(self):
        out = parse_ui_tars_planning(
            "Thought: copy\nAction: hotkey(key='ctrl c')",
            {"width": 800, "height": 600},
        )
        kp = out["actions"][0]
        assert kp["type"] == "KeyboardPress"
        assert kp["param"]["keyName"] == "Control+c"


# --- auto-glm swipe -> scroll -----------------------------------------------

class TestAutoGlmSwipe:
    def _swipe(self, start, end, size=(1000, 1000)):
        parsed = {
            "_metadata": "do",
            "action": "Swipe",
            "start": start,
            "end": end,
            "think": "scroll",
        }
        out = transform_auto_glm_action(
            parsed, {"width": size[0], "height": size[1]}
        )
        return out[0]["param"]

    def test_coordinate_max_is_1000(self):
        assert AUTO_GLM_COORDINATE_MAX == 1000

    def test_finger_up_scrolls_content_down(self):
        # finger 500 -> 200 (up): JS direction = deltaY<0 -> 'down'
        p = self._swipe([500, 500], [500, 200])
        assert p["direction"] == "down"
        assert p["distance"] == 300  # round(300 * 1000 / 1000)

    def test_finger_down_scrolls_content_up(self):
        # finger 200 -> 500 (down): deltaY>0 -> 'up'
        p = self._swipe([500, 200], [500, 500])
        assert p["direction"] == "up"

    def test_finger_left_is_right(self):
        # deltaX<0 -> 'right'
        p = self._swipe([500, 500], [200, 500])
        assert p["direction"] == "right"

    def test_no_50px_floor(self):
        # small swipe scaled delta 20px -> distance 20 (not floored to 50)
        p = self._swipe([500, 500], [500, 480])
        assert p["distance"] == 20

    def test_swipe_attaches_locate_from_start(self):
        p = self._swipe([500, 500], [500, 200])
        assert "locate" in p
        cx, cy = p["locate"]["center"]
        # start (500,500) on 1000x1000 grid/1000 -> (500, 500)
        assert (round(cx), round(cy)) == (500, 500)


# --- Doubao string-array (first-2 like JS) ----------------------------------

class TestDoubaoStringArray:
    def test_multi_number_string_item_takes_first_two(self):
        # ["940 445 969 490"] -> JS keeps [940,445] -> center-point bbox
        result = adapt_doubao_bbox(["940 445 969 490"], 1000, 1000)
        # center (940,445), DEFAULT_BBOX_SIZE=20, half=10
        assert result == (930, 435, 950, 455)

    def test_flat_four_numbers_is_rect(self):
        result = adapt_doubao_bbox([100, 200, 300, 400], 1000, 1000)
        assert result == (100, 200, 300, 400)


# --- format_bbox / adapt_bbox_to_rect min-1 ---------------------------------

class TestRectMinDimensions:
    def test_format_bbox_min_one(self):
        rect = format_bbox((10, 10, 10, 10))
        assert rect["width"] == 1.0
        assert rect["height"] == 1.0

    def test_adapt_bbox_to_rect_min_one(self):
        # qwen2.5-vl pixel pass-through, degenerate point
        rect = adapt_bbox_to_rect(
            [50, 50, 50, 50], 1000, 1000, model_family="qwen2.5-vl"
        )
        assert rect["width"] >= 1.0
        assert rect["height"] >= 1.0


# --- max_tokens omission -----------------------------------------------------

class TestMaxTokens:
    def test_unset_returns_none(self, monkeypatch):
        from pymidscene.shared.env import get_configured_max_tokens
        monkeypatch.delenv("MIDSCENE_MODEL_MAX_TOKENS", raising=False)
        monkeypatch.delenv("OPENAI_MAX_TOKENS", raising=False)
        assert get_configured_max_tokens() is None

    def test_midscene_var_takes_precedence(self, monkeypatch):
        from pymidscene.shared.env import get_configured_max_tokens
        monkeypatch.setenv("MIDSCENE_MODEL_MAX_TOKENS", "8000")
        monkeypatch.setenv("OPENAI_MAX_TOKENS", "2000")
        assert get_configured_max_tokens() == 8000

    def test_openai_fallback(self, monkeypatch):
        from pymidscene.shared.env import get_configured_max_tokens
        monkeypatch.delenv("MIDSCENE_MODEL_MAX_TOKENS", raising=False)
        monkeypatch.setenv("OPENAI_MAX_TOKENS", "5000")
        assert get_configured_max_tokens() == 5000
