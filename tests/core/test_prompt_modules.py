from __future__ import annotations

from pymidscene.core.ai_model.prompts import common
from pymidscene.core.ai_model.prompts.extractor import (
    extract_data_prompt,
    parse_xml_extraction_response,
    system_prompt_to_extract,
)
from pymidscene.core.ai_model.prompts.locator import system_prompt_to_locate_element
from pymidscene.core.ai_model.prompts.planner import system_prompt_to_plan


def test_get_preferred_language_uses_env_override(monkeypatch) -> None:
    monkeypatch.setenv("MIDSCENE_PREFERRED_LANGUAGE", "French")
    monkeypatch.setattr(common, "_local_timezone_name", lambda: "Asia/Shanghai")

    assert common.get_preferred_language() == "French"


def test_get_preferred_language_defaults_by_timezone(monkeypatch) -> None:
    monkeypatch.delenv("MIDSCENE_PREFERRED_LANGUAGE", raising=False)
    monkeypatch.setattr(common, "_local_timezone_name", lambda: "UTC")
    assert common.get_preferred_language() == "English"

    monkeypatch.setattr(common, "_local_timezone_name", lambda: "Asia/Shanghai")
    assert common.get_preferred_language() == "Chinese"


def test_locator_and_planner_prompts_use_preferred_language(monkeypatch) -> None:
    monkeypatch.setenv("MIDSCENE_PREFERRED_LANGUAGE", "English")

    locator_prompt = system_prompt_to_locate_element("gemini")
    planner_prompt = system_prompt_to_plan()

    assert "Use English." in locator_prompt
    assert (
        'box_2d bounding box for the target element, should be '
        '[ymin, xmin, ymax, xmax] normalized to 0-1000.'
    ) in locator_prompt
    assert 'Use English for the "thought" field.' in planner_prompt


def test_system_prompt_to_extract_includes_upstream_scalar_and_array_examples(
    monkeypatch,
) -> None:
    monkeypatch.setenv("MIDSCENE_PREFERRED_LANGUAGE", "English")

    prompt = system_prompt_to_extract()

    assert (
        "<thought>the thinking process of the extraction, less than 300 words. "
        "Use English in this field.</thought>"
    ) in prompt
    assert '["todo 1", "todo 2", "todo 3"]' in prompt
    assert '"todo list"' in prompt
    assert '{ "result": true }' in prompt


def test_extract_data_prompt_can_include_page_description() -> None:
    prompt = extract_data_prompt(
        {"title": "the page title, string"},
        page_description="Todo page with a single list",
    )

    assert "<PageDescription>" in prompt
    assert "Todo page with a single list" in prompt
    assert '"title": "the page title, string"' in prompt


def test_parse_xml_extraction_response_handles_case_insensitive_tags() -> None:
    xml = """
<THOUGHT>Case insensitive thought</THOUGHT>
<DATA-JSON>
{"result": "success"}
</DATA-JSON>
    """.strip()

    result = parse_xml_extraction_response(xml)

    assert result == {
        "thought": "Case insensitive thought",
        "data": {"result": "success"},
    }
