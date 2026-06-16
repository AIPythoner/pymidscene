"""
核心功能横扫对齐(0.x)修复的回归测试:报告 param 形状、数据脚本标签、flush_cache。
"""

from __future__ import annotations

import re

from pymidscene.core.agent.agent import Agent
from pymidscene.core.js_react_report_generator import JSReactReportGenerator


def _last_task(gen: JSReactReportGenerator) -> dict:
    dump = gen._current_dump.to_dict()
    return dump["executions"][-1]["tasks"][-1]


def _all_tasks(gen: JSReactReportGenerator) -> list:
    dump = gen._current_dump.to_dict()
    return [t for ex in dump["executions"] for t in ex["tasks"]]


# --- #6 / #7 report param shape ---------------------------------------------

def test_planning_plan_uses_user_instruction_not_prompt():
    gen = JSReactReportGenerator()
    gen.start_session(group_name="g", description="d")
    gen.add_task(task_type="Planning", sub_type="Plan",
                 prompt="open the cart and report the total", thought="t")
    param = _last_task(gen)["param"]
    assert param.get("userInstruction") == "open the cart and report the total"
    assert "prompt" not in param  # JS paramStr 读 userInstruction,不读 prompt


def test_action_space_omits_phantom_prompt_key():
    gen = JSReactReportGenerator()
    gen.start_session(group_name="g", description="d")
    gen.add_task(task_type="Action Space", sub_type="Tap",
                 prompt="the login button", thought="tapping login")
    param = _last_task(gen).get("param")
    # Action Space 不再塞 phantom 的 prompt 键(空 param 序列化为 None/缺省)
    assert not param or "prompt" not in param


def test_insight_locate_keeps_prompt():
    gen = JSReactReportGenerator()
    gen.start_session(group_name="g", description="d")
    gen.add_task(task_type="Insight", sub_type="Locate",
                 prompt="the cart icon", thought="t")
    assert _last_task(gen)["param"]["prompt"] == "the cart icon"


def test_insight_query_and_assert_keys_unchanged():
    gen = JSReactReportGenerator()
    gen.start_session(group_name="g", description="d")
    gen.add_task(task_type="Insight", sub_type="Query", prompt="the title")
    gen.add_task(task_type="Insight", sub_type="Assert", prompt="cart is shown")
    tasks = _all_tasks(gen)
    assert any((t["param"] or {}).get("dataDemand") == "the title" for t in tasks)
    assert any((t["param"] or {}).get("assertion") == "cart is shown" for t in tasks)


# --- #4 data-script tag shape -----------------------------------------------

def test_data_script_has_two_type_attributes():
    gen = JSReactReportGenerator()
    gen.start_session(group_name="g", description="d")
    gen.add_task(task_type="Insight", sub_type="Query", prompt="x")
    script = gen.generate_data_script()
    assert script.startswith(
        '<script type="midscene_web_dump" type="application/json">'
    )
    # 行首 \n<script + application/json,对齐 JS ReportMergingTool 的提取正则
    html = gen.generate_html()
    assert re.search(
        r'\n<script[^>]*type="midscene_web_dump" type="application/json"[^>]*>',
        html,
    )


# --- #15 flush_cache --------------------------------------------------------

def test_flush_cache_delegates_with_clean_unused():
    agent = object.__new__(Agent)
    calls = []

    class _FakeCache:
        def _flush_cache_to_file(self, clean_unused=False):
            calls.append(clean_unused)

    agent.task_cache = _FakeCache()
    agent.flush_cache(clean_unused=True)
    agent.flush_cache()
    assert calls == [True, False]

    # 无 task_cache 时不报错
    agent.task_cache = None
    agent.flush_cache(clean_unused=True)
