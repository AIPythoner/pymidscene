"""iOS utils 单元测试."""

from __future__ import annotations

import httpx
import pytest

from pymidscene.ios import utils as ios_utils


pytestmark = pytest.mark.asyncio


class TestCheckIOSEnvironment:
    async def test_reachable(self, monkeypatch):
        async def fake_get(self, url, **kw):
            return httpx.Response(
                200, json={"value": {"ready": True}}, request=httpx.Request("GET", url)
            )
        monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
        result = await ios_utils.check_ios_environment()
        assert result["available"] is True
        assert result["status"] == {"value": {"ready": True}}

    async def test_connection_error(self, monkeypatch):
        async def boom(self, url, **kw):
            raise httpx.ConnectError("refused")
        monkeypatch.setattr(httpx.AsyncClient, "get", boom)
        result = await ios_utils.check_ios_environment()
        assert result["available"] is False
        assert "Unable to reach WDA" in result["error"]


class TestAgentFromWebDriverAgent:
    async def test_connects_and_returns_agent(self, monkeypatch, wda_transport):
        from pymidscene.ios import device as device_mod
        from pymidscene.ios.device import IOSDevice, IOSDeviceOpt
        from pymidscene.ios.webdriver_client import IOSWebDriverClient

        created: list[IOSDevice] = []

        real_init = IOSDevice.__init__

        def _init(self, options=None, client=None):
            c = client or IOSWebDriverClient(
                host="fake", port=0, transport=wda_transport
            )
            real_init(self, options=options, client=c)
            created.append(self)

        monkeypatch.setattr(IOSDevice, "__init__", _init)

        # 绕过真实 Agent 构造 (需要模型配置)
        from pymidscene.ios import agent as agent_mod

        class StubAgent:
            def __init__(self, device, **kwargs):
                self.device = device

        monkeypatch.setattr(agent_mod, "IOSAgent", StubAgent)

        agent = await ios_utils.agent_from_webdriver_agent()
        assert agent.device.device_id == "FAKE-UDID-123"
