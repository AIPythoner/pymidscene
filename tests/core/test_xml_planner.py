"""
默认规划器 XML 单动作契约测试([17] 重写)。

覆盖:extract_xml_tag、parse_planning_response 的全部契约点(单动作、
complete-task 成败、缺 log、null 动作、action+complete 冲突、(x,y) 简写、
normalize trim、error 标签),以及 _ai_act_xml_loop 单动作 replan 循环
(单动作/轮、complete-task 终止、动作聚合、对话历史含截图与上一轮 XML、
error/finalize=false 抛错、_snapshot_history 截图裁剪)。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from pymidscene.core.agent import agent as agent_module
from pymidscene.core.agent.agent import Agent
from pymidscene.core.ai_model.prompts.planner import (
    extract_xml_tag,
    parse_planning_response,
    system_prompt_to_plan,
)

# --- extract_xml_tag ---------------------------------------------------------

class TestExtractXmlTag:
    def test_basic(self):
        assert extract_xml_tag("<log>hello</log>", "log") == "hello"

    def test_case_insensitive_and_trim(self):
        assert extract_xml_tag("<LOG>  hi  </LOG>", "log") == "hi"

    def test_missing_returns_none(self):
        assert extract_xml_tag("<log>x</log>", "note") is None

    def test_non_greedy_first_match(self):
        assert extract_xml_tag("<a>1</a><a>2</a>", "a") == "1"


# --- parse_planning_response -------------------------------------------------

class TestParseXmlPlanning:
    def test_single_action(self):
        xml = (
            "<thought>type the query</thought>"
            "<log>Type into search</log>"
            "<action-type>Input</action-type>"
            '<action-param-json>{"locate": {"prompt": "search box"}, '
            '"value": "hi"}</action-param-json>'
        )
        res = parse_planning_response(xml)
        assert res["shouldContinuePlanning"] is True
        assert len(res["actions"]) == 1
        a = res["actions"][0]
        assert a["type"] == "Input"
        assert a["param"]["locate"]["prompt"] == "search box"
        assert a["param"]["value"] == "hi"
        assert a["thought"] == "type the query"

    def test_complete_task_success_true(self):
        xml = '<log>done</log><complete-task success="true">42</complete-task>'
        res = parse_planning_response(xml)
        assert res["actions"] == []
        assert res["shouldContinuePlanning"] is False
        assert res["finalizeSuccess"] is True
        assert res["finalizeMessage"] == "42"

    def test_complete_task_success_false(self):
        xml = '<log>oops</log><complete-task success="false">no button</complete-task>'
        res = parse_planning_response(xml)
        assert res["finalizeSuccess"] is False
        assert res["finalizeMessage"] == "no button"
        assert res["shouldContinuePlanning"] is False

    def test_missing_log_raises(self):
        with pytest.raises(ValueError, match="Missing required field: log"):
            parse_planning_response("<action-type>Tap</action-type>")

    def test_action_type_null_is_no_action(self):
        res = parse_planning_response("<log>nothing</log><action-type>null</action-type>")
        assert res["actions"] == []
        assert res["shouldContinuePlanning"] is True  # no complete-task

    def test_action_and_complete_conflict_action_wins(self):
        xml = (
            "<log>x</log><action-type>Tap</action-type>"
            '<action-param-json>{"locate": {"prompt": "b"}}</action-param-json>'
            '<complete-task success="true">ignored</complete-task>'
        )
        res = parse_planning_response(xml)
        assert len(res["actions"]) == 1
        # complete-task dropped -> keep planning
        assert res["finalizeSuccess"] is None
        assert res["shouldContinuePlanning"] is True

    def test_point_shortcut_param(self):
        xml = (
            "<log>tap</log><action-type>Tap</action-type>"
            "<action-param-json>(100,200)</action-param-json>"
        )
        res = parse_planning_response(xml)
        assert res["actions"][0]["param"] == [100, 200]

    def test_normalize_trims_keys_and_values(self):
        xml = (
            "<log>x</log><action-type>Input</action-type>"
            '<action-param-json>{" value ": "  hi  "}</action-param-json>'
        )
        res = parse_planning_response(xml)
        assert res["actions"][0]["param"] == {"value": "hi"}

    def test_error_tag_extracted(self):
        xml = "<log>x</log><error>something broke</error><action-type>null</action-type>"
        res = parse_planning_response(xml)
        assert res["error"] == "something broke"

    def test_note_extracted(self):
        xml = "<log>x</log><note>remember the total is 42</note><action-type>null</action-type>"
        res = parse_planning_response(xml)
        assert res["note"] == "remember the total is 42"

    def test_code_fenced_param(self):
        xml = (
            "<log>x</log><action-type>KeyboardPress</action-type>"
            "<action-param-json>```json\n{\"keyName\": \"Enter\"}\n```"
            "</action-param-json>"
        )
        res = parse_planning_response(xml)
        assert res["actions"][0]["param"] == {"keyName": "Enter"}

    def test_param_json_repaired(self):
        # 借道 safe_parse_json_with_repair:LLM 常见的尾逗号能被修好(此前手搓
        # 的弱解析会直接报错并把任务判失败)
        xml = (
            "<log>x</log><action-type>KeyboardPress</action-type>"
            '<action-param-json>{"keyName": "Enter",}</action-param-json>'
        )
        res = parse_planning_response(xml)
        assert res["actions"][0]["param"] == {"keyName": "Enter"}

    def test_complete_task_uppercase_true_is_not_success(self):
        # 对齐 JS 的精确比较:只有字面小写 "true" 算成功
        xml = '<log>x</log><complete-task success="TRUE">m</complete-task>'
        res = parse_planning_response(xml)
        assert res["finalizeSuccess"] is False
        assert res["shouldContinuePlanning"] is False


def test_system_prompt_is_xml_contract():
    p = system_prompt_to_plan()
    assert "<action-type>" in p
    assert "<action-param-json>" in p
    assert "<complete-task" in p
    assert "next ONE action" in p


def test_readable_time_has_format_suffix():
    assert Agent._readable_time().endswith("(YYYY-MM-DD HH:mm:ss)")


def test_longpress_and_assert_survive_cache_roundtrip():
    # 这两类动作被默认 XML planner 规划,必须能进/出缓存(不被静默丢步骤)
    agent = object.__new__(Agent)
    actions = [
        {"type": "LongPress",
         "param": {"locate": {"prompt": "the handle"}, "duration": 600},
         "thought": ""},
        {"type": "Assert", "param": {"condition": "the menu is open"},
         "thought": ""},
        {"type": "Tap", "param": {"locate": {"prompt": "ok"}}, "thought": ""},
    ]
    yaml_wf = agent._actions_to_yaml_workflow(actions, "do it")
    parsed = agent._parse_cached_workflow(yaml_wf)
    assert [a["type"] for a in parsed] == ["LongPress", "Assert", "Tap"]
    assert parsed[0]["param"]["locate"] == "the handle"  # locator 降级为 prompt
    assert parsed[0]["param"]["duration"] == 600
    assert parsed[1]["param"]["condition"] == "the menu is open"


# --- _snapshot_history -------------------------------------------------------

def _img(tag):
    return {
        "role": "user",
        "content": [
            {"type": "text", "text": tag},
            {"type": "image_url", "image_url": {"url": f"data:img;{tag}"}},
        ],
    }


class TestSnapshotHistory:
    def test_keeps_only_last_n_images(self):
        history = [_img("a"), _img("b"), _img("c")]
        snap = Agent._snapshot_history(history, max_images=2)
        # oldest (a) image replaced by placeholder text; b, c keep images
        kinds = [
            [part["type"] for part in m["content"]] for m in snap
        ]
        assert kinds[0] == ["text", "text"]  # a's image downgraded
        assert kinds[1] == ["text", "image_url"]
        assert kinds[2] == ["text", "image_url"]

    def test_does_not_mutate_original(self):
        history = [_img("a"), _img("b"), _img("c")]
        Agent._snapshot_history(history, max_images=1)
        assert history[0]["content"][1]["type"] == "image_url"

    def test_none_means_unlimited(self):
        history = [_img("a"), _img("b")]
        snap = Agent._snapshot_history(history, max_images=None)
        assert all(m["content"][1]["type"] == "image_url" for m in snap)


# --- _ai_act_xml_loop integration -------------------------------------------

def _make_agent():
    agent = object.__new__(Agent)
    agent.session_recorder = None
    agent.recorder = None
    return agent


def _install(agent, responses):
    """装上假的截图 / AI 调用 / 执行器,返回 (calls, executed) 记录。"""
    state = {"i": 0, "messages": []}
    executed: list = []

    async def _shot():
        return ("B64", {"width": 100, "height": 100})

    async def _call(messages, intent):
        state["messages"].append(messages)
        i = state["i"]
        state["i"] += 1
        return {"content": responses[i], "usage": None}

    async def _exec(action_type, param):
        executed.append((action_type, param))
        return True

    agent._capture_ai_screenshot = _shot
    agent._call_ai_with_config_async = _call
    agent._execute_planned_action = _exec
    return state, executed


_CFG = SimpleNamespace(model_family="qwen2.5-vl", model_name="test")


@pytest.fixture(autouse=True)
def _fast_sleep(monkeypatch):
    async def _noop(*a, **k):
        return None

    monkeypatch.setattr(agent_module.asyncio, "sleep", _noop)


@pytest.mark.asyncio
async def test_loop_single_action_then_complete():
    agent = _make_agent()
    responses = [
        "<log>type</log><action-type>Input</action-type>"
        '<action-param-json>{"locate": {"prompt": "box"}, "value": "hi"}'
        "</action-param-json>",
        '<log>done</log><complete-task success="true">ok</complete-task>',
    ]
    state, executed = _install(agent, responses)
    result = await agent._ai_act_xml_loop("do it", _CFG, 20)
    assert state["i"] == 2  # two AI calls: one action + one complete
    assert len(executed) == 1
    assert executed[0][0] == "Input"
    assert len(result) == 1  # one action aggregated for cache


@pytest.mark.asyncio
async def test_loop_history_carries_screenshots_and_prior_xml():
    agent = _make_agent()
    responses = [
        "<log>step1</log><action-type>Tap</action-type>"
        '<action-param-json>{"locate": {"prompt": "a"}}</action-param-json>',
        '<log>done</log><complete-task success="true">ok</complete-task>',
    ]
    state, _ = _install(agent, responses)
    await agent._ai_act_xml_loop("do it", _CFG, 20)
    # the 2nd AI call's messages must contain the assistant's first raw XML
    second_msgs = state["messages"][1]
    roles = [m["role"] for m in second_msgs]
    assert roles[0] == "system"
    assert "assistant" in roles
    assistant_msg = next(m for m in second_msgs if m["role"] == "assistant")
    assert "step1" in assistant_msg["content"]
    # and at least one screenshot image present
    has_image = any(
        isinstance(m.get("content"), list)
        and any(p.get("type") == "image_url" for p in m["content"])
        for m in second_msgs
    )
    assert has_image


@pytest.mark.asyncio
async def test_loop_complete_false_raises():
    agent = _make_agent()
    responses = ['<log>fail</log><complete-task success="false">no element</complete-task>']
    _install(agent, responses)
    with pytest.raises(RuntimeError, match="Task failed: no element"):
        await agent._ai_act_xml_loop("do it", _CFG, 20)


@pytest.mark.asyncio
async def test_loop_error_tag_raises():
    agent = _make_agent()
    responses = ["<log>broke</log><error>fatal</error><action-type>null</action-type>"]
    _install(agent, responses)
    with pytest.raises(RuntimeError, match="Failed to continue: fatal"):
        await agent._ai_act_xml_loop("do it", _CFG, 20)


@pytest.mark.asyncio
async def test_loop_replan_limit_raises():
    agent = _make_agent()
    # always returns an action, never completes -> must hit the cycle limit
    action_resp = (
        "<log>again</log><action-type>Tap</action-type>"
        '<action-param-json>{"locate": {"prompt": "x"}}</action-param-json>'
    )
    _install(agent, [action_resp] * 10)
    with pytest.raises(RuntimeError, match="Max replan cycles"):
        await agent._ai_act_xml_loop("do it", _CFG, 3)


@pytest.mark.asyncio
async def test_loop_action_failure_then_recover():
    agent = _make_agent()
    responses = [
        "<log>try</log><action-type>Tap</action-type>"
        '<action-param-json>{"locate": {"prompt": "x"}}</action-param-json>',
        '<log>done</log><complete-task success="true">ok</complete-task>',
    ]
    state = {"i": 0, "messages": []}
    calls: list = []

    async def _shot():
        return ("B64", {"width": 10, "height": 10})

    async def _call(messages, intent):
        state["messages"].append(messages)
        i = state["i"]
        state["i"] += 1
        return {"content": responses[i], "usage": None}

    async def _exec(action_type, param):
        calls.append(action_type)
        return False  # first (and only) action fails

    agent._capture_ai_screenshot = _shot
    agent._call_ai_with_config_async = _call
    agent._execute_planned_action = _exec

    result = await agent._ai_act_xml_loop("do it", _CFG, 20)
    # failed action is NOT aggregated for cache; loop still completes via complete-task
    assert result == []
    # the 2nd call's MOST RECENT user feedback should mention the execution error
    second_msgs = state["messages"][1]
    feedback = [
        m for m in second_msgs
        if m["role"] == "user" and isinstance(m["content"], list)
    ][-1]
    feedback_text = feedback["content"][0]["text"]
    assert "error executing" in feedback_text.lower()
