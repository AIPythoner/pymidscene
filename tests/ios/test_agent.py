"""IOSAgent 组合行为测试."""

from __future__ import annotations

import httpx
import pytest
import pytest_asyncio

from pymidscene.ios.agent import IOSAgent


class _StubInnerAgent:
    def __init__(self):
        self.calls = []
        self.session_recorder = None
        self.recorder = None

    async def ai_locate(self, d):
        self.calls.append(("ai_locate", d))
        return None

    async def ai_click(self, d):
        self.calls.append(("ai_click", d))
        return True

    async def ai_input(self, d, t):
        self.calls.append(("ai_input", d, t))
        return True

    async def ai_query(self, s, use_cache=True):
        self.calls.append(("ai_query", s, use_cache))
        return {"ok": 1}

    async def ai_assert(self, a, e=""):
        self.calls.append(("ai_assert", a, e))
        return True

    async def ai_act(self, a):
        self.calls.append(("ai_act", a))
        return True

    async def ai_wait_for(self, a, t, i):
        self.calls.append(("ai_wait_for", a, t, i))
        return True

    async def ai_scroll(self, *args):
        self.calls.append(("ai_scroll", *args))
        return True

    def finish(self):
        self.calls.append(("finish",))
        return "/tmp/report.html"

    def save_report(self):
        return "/tmp/report.html"

    def get_report_dir(self):
        return "/tmp"

    def get_cache_stats(self):
        return None


@pytest_asyncio.fixture
async def ios_agent(ios_device, monkeypatch):
    """IOSAgent 实例, 内部 core Agent 替换为 stub."""
    stub = _StubInnerAgent()
    from pymidscene.ios import agent as agent_mod

    class FakeCore:
        def __new__(cls, **kw):
            return stub

    monkeypatch.setattr(agent_mod, "Agent", FakeCore)
    agent = IOSAgent(ios_device)
    agent._stub = stub
    return agent


@pytest.mark.asyncio
class TestAIForwarding:
    async def test_ai_click_forwards(self, ios_agent):
        await ios_agent.ai_click("按钮")
        assert ios_agent._stub.calls[-1][0] == "ai_click"

    async def test_ai_tap_alias_for_click(self, ios_agent):
        await ios_agent.ai_tap("button")
        names = [c[0] for c in ios_agent._stub.calls]
        assert "ai_click" in names

    async def test_ai_input_forwards(self, ios_agent):
        await ios_agent.ai_input("框", "text")
        assert ios_agent._stub.calls[-1][0] == "ai_input"

    async def test_finish(self, ios_agent):
        assert ios_agent.finish() == "/tmp/report.html"


@pytest.mark.asyncio
class TestIOSSpecificForwarding:
    async def test_home(self, ios_agent, fake_wda):
        await ios_agent.home()
        assert fake_wda.calls_for("POST", "/wda/pressButton")

    async def test_app_switcher(self, ios_agent, fake_wda):
        await ios_agent.app_switcher()
        assert fake_wda.calls_for("POST", "/actions")

    async def test_launch_url(self, ios_agent, fake_wda):
        await ios_agent.launch("https://example.com")
        assert fake_wda.calls_for("POST", "/url")

    async def test_run_wda_request_passes_through(self, ios_agent, fake_wda):
        fake_wda.on(
            "GET",
            r"^/test$",
            lambda req: httpx.Response(200, json={"value": {"x": 1}}),
        )
        out = await ios_agent.run_wda_request("GET", "/test")
        assert isinstance(out, dict)


@pytest.mark.asyncio
class TestContextManager:
    async def test_aexit_finishes_and_destroys(self, ios_agent, fake_wda):
        async with ios_agent as a:
            assert a is ios_agent
        names = [c[0] for c in ios_agent._stub.calls]
        assert "finish" in names
        # 退出时应当 DELETE session
        assert fake_wda.calls_for("DELETE", "/session/")


class TestAppNameMapping:
    def test_constructor_merges_user_mapping(self, ios_device):
        # 用 stub 跳过 Agent 初始化
        from unittest.mock import patch
        from pymidscene.ios.agent import IOSAgent

        with patch(
            "pymidscene.ios.agent.Agent", new=lambda **kw: _StubInnerAgent()
        ):
            IOSAgent(ios_device, app_name_mapping={"CustomApp": "com.custom"})
        assert ios_device._app_name_mapping.get("CustomApp") == "com.custom"
        # 默认映射保留
        assert ios_device._app_name_mapping.get("微信") == "com.tencent.xin"
