"""
plan 缓存 yaml workflow 的 JS 互通格式测试.

写入必须是 JS `MidsceneYamlScript`(agent.ts:948-957)结构;
读取需同时兼容 JS 格式与 0.3.1 之前的 Python 裸列表格式.
"""

from __future__ import annotations

import yaml

from pymidscene.core.agent.agent import Agent


def make_agent() -> Agent:
    # 这些方法不依赖 __init__ 状态, 绕过模型配置直接测
    return object.__new__(Agent)


class TestParseCachedWorkflow:
    def test_parses_js_midscene_yaml_script(self):
        agent = make_agent()
        yaml_text = """
tasks:
  - name: login
    flow:
      - aiTap: ''
        locate: login button
      - aiInput: ''
        value: hello
        locate: search box
      - sleep: 2000
"""
        actions = agent._parse_cached_workflow(yaml_text)
        assert actions == [
            {"type": "Tap", "param": {"locate": "login button"}},
            {
                "type": "Input",
                "param": {"value": "hello", "locate": "search box"},
            },
            {"type": "Sleep", "param": {"timeMs": 2000}},
        ]

    def test_parses_yaml_script_shorthand_locate(self):
        # yaml 脚本常见简写: aiTap 的值即 locate prompt
        agent = make_agent()
        actions = agent._parse_cached_workflow(
            "tasks:\n  - name: t\n    flow:\n      - aiTap: 'login button'\n"
        )
        assert actions == [
            {"type": "Tap", "param": {"locate": "login button"}}
        ]

    def test_parses_legacy_python_list_format(self):
        agent = make_agent()
        legacy = "- type: Tap\n  param:\n    locate: btn\n  thought: t\n"
        actions = agent._parse_cached_workflow(legacy)
        assert actions is not None
        assert actions[0]["type"] == "Tap"

    def test_unrecognized_shape_returns_none(self):
        agent = make_agent()
        assert agent._parse_cached_workflow("just a string") is None


class TestActionsToYamlWorkflow:
    def test_writes_js_compatible_script(self):
        agent = make_agent()
        out = agent._actions_to_yaml_workflow(
            [
                {
                    "type": "Tap",
                    "param": {
                        "locate": {"prompt": "login button", "center": [1, 2]}
                    },
                    "thought": "ignored in yaml flow",
                },
                {"type": "Sleep", "param": {"timeMs": 500}},
            ],
            "do login",
        )
        data = yaml.safe_load(out)
        assert data["tasks"][0]["name"] == "do login"
        flow = data["tasks"][0]["flow"]
        # locator 字段降为 prompt 字符串(对齐 JS dumpActionParam)
        assert flow[0] == {"aiTap": "", "locate": "login button"}
        assert flow[1] == {"Sleep": "", "timeMs": 500}

    def test_roundtrip(self):
        agent = make_agent()
        out = agent._actions_to_yaml_workflow(
            [
                {
                    "type": "Input",
                    "param": {
                        "value": "你好",
                        "locate": {"prompt": "搜索框"},
                    },
                }
            ],
            "搜索",
        )
        actions = agent._parse_cached_workflow(out)
        assert actions == [
            {"type": "Input", "param": {"value": "你好", "locate": "搜索框"}}
        ]

    def test_unknown_action_type_is_skipped(self):
        agent = make_agent()
        out = agent._actions_to_yaml_workflow(
            [{"type": "Finished", "param": {}}], "t"
        )
        assert yaml.safe_load(out)["tasks"][0]["flow"] == []
