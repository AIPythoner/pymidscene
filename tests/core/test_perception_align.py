"""
感知层 JS 对齐修复的回归测试(Batch A):
- 提取响应走 safe_parse_json_with_repair(去代码块围栏 + 修复)
- extract_data_prompt 始终输出 <PageDescription> 块
- ai_boolean/number/string 用 `result` 键 + 大写类型前缀(对齐 JS createTypeQueryTask)
- _build_messages 的截图带 detail:"high"
"""

from __future__ import annotations

import pytest

from pymidscene.core.agent.agent import Agent
from pymidscene.core.ai_model.prompts.extractor import (
    extract_data_prompt,
    parse_xml_extraction_response,
)

# --- #1 extraction parse robustness -----------------------------------------

class TestExtractionParse:
    def test_code_fenced_data_json_is_unwrapped(self):
        xml = (
            "<thought>t</thought>"
            "<data-json>```json\n{\"title\": \"hi\"}\n```</data-json>"
        )
        res = parse_xml_extraction_response(xml)
        assert res["data"] == {"title": "hi"}

    def test_trailing_comma_repaired(self):
        xml = '<data-json>{"a": 1, "b": 2,}</data-json>'
        res = parse_xml_extraction_response(xml)
        assert res["data"] == {"a": 1, "b": 2}

    def test_scalar_data_json_still_works(self):
        # data-json 合法地可以是裸标量(JS 测试里有 42 / "todo list" / true)
        assert parse_xml_extraction_response("<data-json>42</data-json>")["data"] == 42
        assert parse_xml_extraction_response(
            '<data-json>true</data-json>'
        )["data"] is True

    def test_missing_data_json_raises(self):
        with pytest.raises(ValueError, match="data-json"):
            parse_xml_extraction_response("<thought>t</thought>")


# --- #11 PageDescription always emitted -------------------------------------

class TestPageDescription:
    def test_always_emitted_even_when_absent(self):
        p = extract_data_prompt({"title": "the title"})
        assert "<PageDescription>" in p
        assert "</PageDescription>" in p
        assert "<DATA_DEMAND>" in p

    def test_included_when_given(self):
        p = extract_data_prompt({"x": "y"}, page_description="A todo page")
        assert "A todo page" in p
        assert "<PageDescription>\nA todo page\n</PageDescription>" in p


# --- #3 typed-query demand key/prefix ---------------------------------------

class TestTypedQueryDemand:
    @pytest.mark.asyncio
    async def test_ai_boolean_uses_result_key_and_capitalized_type(self):
        agent = object.__new__(Agent)
        captured = {}

        async def _fake_query(demand, use_cache=True):
            captured["demand"] = demand
            return {"data": {"result": True}}

        agent.ai_query = _fake_query  # type: ignore[method-assign]
        result = await agent.ai_boolean("is it the home page?")
        assert result is True
        assert captured["demand"] == {"result": "Boolean, is it the home page?"}

    @pytest.mark.asyncio
    async def test_ai_number_reads_result_key(self):
        agent = object.__new__(Agent)
        captured = {}

        async def _fake_query(demand, use_cache=True):
            captured["demand"] = demand
            return {"data": {"result": "42"}}

        agent.ai_query = _fake_query  # type: ignore[method-assign]
        result = await agent.ai_number("how many items?")
        assert result == 42.0
        assert captured["demand"] == {"result": "Number, how many items?"}

    @pytest.mark.asyncio
    async def test_ai_string_reads_result_key(self):
        agent = object.__new__(Agent)

        async def _fake_query(demand, use_cache=True):
            assert demand == {"result": "String, the page title?"}
            return {"data": {"result": "Welcome"}}

        agent.ai_query = _fake_query  # type: ignore[method-assign]
        assert await agent.ai_string("the page title?") == "Welcome"


# --- #14 image detail:high --------------------------------------------------

def test_build_messages_image_detail_high():
    agent = object.__new__(Agent)
    msgs = agent._build_messages("sys prompt", "user prompt", "B64DATA")
    image_part = msgs[1]["content"][0]
    assert image_part["type"] == "image_url"
    assert image_part["image_url"]["detail"] == "high"
    assert "B64DATA" in image_part["image_url"]["url"]
