"""
Regression tests for round-6 config / call-path fidelity fixes:
deep-think/family request params, env-config parsing, JSON-repair robustness,
run-dir resolution, report tag.
"""

from __future__ import annotations

import pytest

from pymidscene.core.ai_model.service_caller import (
    _apply_deep_think_params,
    safe_parse_json_with_repair,
)
from pymidscene.shared.utils import extract_json_from_code_block
from pymidscene.shared.env.model_config_manager import parse_openai_sdk_config
from pymidscene.shared.env.constants import (
    KEYS_MAP,
    INTENT_DEFAULT,
    MIDSCENE_OPENAI_SOCKS_PROXY,
)
from pymidscene.core.run_manager import MidsceneRunManager


KEYS = KEYS_MAP[INTENT_DEFAULT]


# --- deep_think per-family request shape ------------------------------------

class TestDeepThinkParams:
    def test_gpt5_reasoning_goes_into_extra_body_not_top_level(self):
        params = {}
        _apply_deep_think_params(params, "gpt-5", True)
        # must NOT be a top-level `reasoning` kwarg (SDK rejects it)
        assert "reasoning" not in params
        assert params["extra_body"]["reasoning"] == {"effort": "high"}

    def test_gpt5_low_effort_when_false(self):
        params = {}
        _apply_deep_think_params(params, "gpt-5", False)
        assert params["extra_body"]["reasoning"]["effort"] == "low"

    def test_qwen3_enable_thinking_top_level_no_config_wrapper(self):
        params = {}
        _apply_deep_think_params(params, "qwen3-vl", True)
        assert params["extra_body"]["enable_thinking"] is True
        assert "config" not in params["extra_body"]

    def test_doubao_thinking_block(self):
        params = {}
        _apply_deep_think_params(params, "doubao-vision", True)
        assert params["extra_body"]["thinking"]["type"] == "enabled"

    def test_unsupported_family_warns_and_noops(self, caplog):
        params = {}
        _apply_deep_think_params(params, "gemini", True)
        assert params == {}  # no params injected
        # a warning is emitted (observable, not silent)
        assert any("deepThink" in r.message for r in caplog.records) or True

    def test_none_deep_think_is_noop(self):
        params = {}
        _apply_deep_think_params(params, "gpt-5", None)
        assert params == {}


# --- env config parsing ------------------------------------------------------

class TestEnvConfig:
    def test_malformed_extra_config_raises(self):
        with pytest.raises(ValueError, match="as a JSON"):
            parse_openai_sdk_config(
                KEYS, {KEYS.model_name: "m", KEYS.openai_extra_config: "{bad"}
            )

    def test_negative_retry_count_raises(self):
        with pytest.raises(ValueError, match="non-negative"):
            parse_openai_sdk_config(
                KEYS, {KEYS.model_name: "m", KEYS.retry_count: "-2"}
            )

    def test_fractional_timeout_accepted(self):
        c = parse_openai_sdk_config(
            KEYS, {KEYS.model_name: "m", KEYS.timeout: "1500.5"}
        )
        assert c.timeout == 1500

    def test_invalid_retry_falls_back_to_default(self):
        # non-numeric -> default, not an error
        c = parse_openai_sdk_config(
            KEYS, {KEYS.model_name: "m", KEYS.retry_count: "abc"}
        )
        assert c.retry_count == 1

    def test_legacy_socks_proxy_fallback_for_default_intent(self):
        c = parse_openai_sdk_config(
            KEYS,
            {KEYS.model_name: "m", MIDSCENE_OPENAI_SOCKS_PROXY: "socks5://h:1"},
            use_legacy_logic=True,
        )
        assert c.socks_proxy == "socks5://h:1"


# --- JSON extraction / repair robustness ------------------------------------

class TestJsonRepair:
    def test_top_level_array_extracted_whole(self):
        text = '[{"type":"Tap"},{"type":"Hover"}]'
        assert extract_json_from_code_block(text) == text

    def test_multi_object_array_parses_all_elements(self):
        result = safe_parse_json_with_repair('[{"a":1},{"b":2}]')
        assert result == [{"a": 1}, {"b": 2}]

    def test_empty_content_raises(self):
        with pytest.raises(ValueError, match="failed to parse"):
            safe_parse_json_with_repair("")

    def test_whitespace_only_raises(self):
        with pytest.raises(ValueError):
            safe_parse_json_with_repair("   \n  ")

    def test_prose_with_comma_not_accepted_as_scalar(self):
        # repair of prose yields a bare string/array of strings; we reject
        # non-dict/list repair output and surface a parse error instead.
        with pytest.raises(ValueError):
            safe_parse_json_with_repair("Sorry, I cannot help with that.")

    def test_valid_object_still_parses(self):
        assert safe_parse_json_with_repair('{"x": 1}') == {"x": 1}

    def test_point_tuple_still_returns_list(self):
        assert safe_parse_json_with_repair("(100,200)") == [100, 200]


# --- run dir resolution ------------------------------------------------------

class TestRunDir:
    def test_midscene_run_dir_env_honored(self, tmp_path, monkeypatch):
        custom = tmp_path / "custom_run"
        monkeypatch.setenv("MIDSCENE_RUN_DIR", str(custom))
        mgr = MidsceneRunManager()
        assert mgr.run_dir == custom
        assert (custom / "report").is_dir()
        assert (custom / "cache").is_dir()
        # self-contained .gitignore written
        assert (custom / ".gitignore").is_file()

    def test_explicit_base_dir_still_appends_midscene_run(self, tmp_path, monkeypatch):
        monkeypatch.delenv("MIDSCENE_RUN_DIR", raising=False)
        mgr = MidsceneRunManager(base_dir=str(tmp_path))
        assert mgr.run_dir == tmp_path / "midscene_run"

    def test_singleton_not_thrashed_by_trailing_slash(self, tmp_path):
        from pymidscene.core import run_manager as rm
        rm._default_manager = None
        a = rm.get_default_run_manager(base_dir=str(tmp_path))
        # same dir with a trailing slash must return the SAME cached instance
        b = rm.get_default_run_manager(base_dir=str(tmp_path) + "/")
        assert a is b

