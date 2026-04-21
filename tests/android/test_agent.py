"""AndroidAgent 的组合行为测试 (大多数 ai_* 方法直接透传, 轻量覆盖)."""

from __future__ import annotations

import pytest

from pymidscene.android.agent import AndroidAgent
from pymidscene.android.device import AndroidDevice


pytestmark = pytest.mark.asyncio


class _StubInnerAgent:
    """替换 core Agent. 记录调用并返回预设值."""

    def __init__(self):
        self.calls: list[tuple[str, tuple, dict]] = []
        self.session_recorder = None
        self.recorder = None

    def _record(self, name, *args, **kwargs):
        self.calls.append((name, args, kwargs))

    async def ai_locate(self, d):
        self._record("ai_locate", d)
        return None

    async def ai_click(self, d):
        self._record("ai_click", d)
        return True

    async def ai_input(self, d, t):
        self._record("ai_input", d, t)
        return True

    async def ai_query(self, schema, use_cache=True):
        self._record("ai_query", schema, use_cache)
        return {"ok": 1}

    async def ai_assert(self, a, e=""):
        self._record("ai_assert", a, e)
        return True

    async def ai_act(self, a):
        self._record("ai_act", a)
        return True

    async def ai_wait_for(self, a, timeout, interval):
        self._record("ai_wait_for", a, timeout, interval)
        return True

    async def ai_scroll(self, direction, distance, scroll_type, locate_prompt):
        self._record("ai_scroll", direction, distance, scroll_type, locate_prompt)
        return True

    def finish(self):
        self._record("finish")
        return "/tmp/report.html"

    def save_report(self):
        return "/tmp/report.html"

    def get_report_dir(self):
        return "/tmp"

    def get_cache_stats(self):
        return {"hits": 0}


import pytest_asyncio


@pytest_asyncio.fixture
async def android_agent(android_device, monkeypatch):
    """AndroidAgent 实例, 内部 core Agent 替换为 stub, device 已 connect."""
    stub = _StubInnerAgent()
    from pymidscene.android import agent as agent_mod

    class FakeCore:
        def __new__(cls, **kw):
            return stub

    monkeypatch.setattr(agent_mod, "Agent", FakeCore)
    await android_device.connect()
    agent = AndroidAgent(android_device)
    agent._stub = stub  # 测试方便
    return agent


class TestTransparentForwarding:
    async def test_ai_click_forwards(self, android_agent):
        ok = await android_agent.ai_click("按钮")
        assert ok is True
        assert android_agent._stub.calls[-1][0] == "ai_click"

    async def test_ai_tap_is_alias_for_click(self, android_agent):
        await android_agent.ai_tap("button")
        # tap 调用底层 ai_click
        names = [c[0] for c in android_agent._stub.calls]
        assert "ai_click" in names

    async def test_ai_input_forwards(self, android_agent):
        await android_agent.ai_input("框", "text")
        assert android_agent._stub.calls[-1][0] == "ai_input"

    async def test_ai_scroll_forwards_all_args(self, android_agent):
        await android_agent.ai_scroll("down", 400, "singleAction", None)
        name, args, _ = android_agent._stub.calls[-1]
        assert name == "ai_scroll"
        assert args == ("down", 400, "singleAction", None)

    async def test_finish_calls_inner(self, android_agent):
        assert android_agent.finish() == "/tmp/report.html"


class TestAndroidSpecificForwarding:
    async def test_back_calls_device(self, android_agent, fake_adb_device):
        await android_agent.back()
        assert any("keyevent 4" in c for c in fake_adb_device.shell_calls)

    async def test_home_calls_device(self, android_agent, fake_adb_device):
        await android_agent.home()
        assert any("keyevent 3" in c for c in fake_adb_device.shell_calls)

    async def test_recent_apps_calls_device(self, android_agent, fake_adb_device):
        await android_agent.recent_apps()
        assert any("keyevent 187" in c for c in fake_adb_device.shell_calls)

    async def test_launch_forwards_to_device(
        self, android_agent, fake_adb_device
    ):
        await android_agent.launch("https://example.com")
        assert any("am start" in c for c in fake_adb_device.shell_calls)

    async def test_run_adb_shell_forwards(
        self, android_agent, fake_adb_device
    ):
        fake_adb_device.on_shell(r"echo hi", "hi")
        out = await android_agent.run_adb_shell("echo hi")
        assert out == "hi"

    async def test_drag_and_drop_issues_swipe(
        self, android_agent, fake_adb_device
    ):
        await android_agent.drag_and_drop((0, 0), (100, 100))
        assert any("input swipe" in c for c in fake_adb_device.shell_calls)


class TestContextManager:
    async def test_finish_called_on_exit(self, android_agent):
        async with android_agent as a:
            assert a is android_agent
        # __aexit__ 调了 finish
        names = [c[0] for c in android_agent._stub.calls]
        assert "finish" in names

    async def test_app_name_mapping_merged_through_agent(
        self, android_device
    ):
        # 重新构造以覆盖 __init__ 中的 mapping 合并分支
        from pymidscene.android.agent import AndroidAgent
        from unittest.mock import patch

        with patch("pymidscene.android.agent.Agent", new=lambda **kw: _StubInnerAgent()):
            AndroidAgent(
                android_device,
                app_name_mapping={"CustomApp": "com.custom"},
            )
        assert "CustomApp" in android_device._app_name_mapping
        # 默认 mapping 也必须保留
        assert "小红书" in android_device._app_name_mapping
