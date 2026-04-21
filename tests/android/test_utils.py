"""get_connected_devices / agent_from_adb_device 的单元测试."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from pymidscene.android import utils as android_utils
from pymidscene.android.utils import ConnectedDevice, get_connected_devices


pytestmark = pytest.mark.asyncio


class _FakeInfo:
    def __init__(self, serial: str, state: str):
        self.serial = serial
        self.state = state


class _FakeAdbClient:
    def __init__(self, infos: list[_FakeInfo]):
        self._infos = infos

    def list(self):
        return self._infos


class TestGetConnectedDevices:
    async def test_returns_mapped_devices(self, monkeypatch):
        fake = _FakeAdbClient([
            _FakeInfo("emulator-5554", "device"),
            _FakeInfo("R58N12345", "unauthorized"),
        ])
        monkeypatch.setattr(
            android_utils, "_list_devices_sync",
            lambda: [
                ConnectedDevice(udid=i.serial, state=i.state)
                for i in fake.list()
            ],
        )
        monkeypatch.setattr(android_utils, "_HAS_ADBUTILS", True)
        devices = await get_connected_devices()
        assert len(devices) == 2
        assert devices[0].udid == "emulator-5554"
        assert devices[0].state == "device"

    async def test_errors_are_wrapped(self, monkeypatch):
        def boom():
            raise RuntimeError("adb not running")
        monkeypatch.setattr(android_utils, "_list_devices_sync", boom)
        monkeypatch.setattr(android_utils, "_HAS_ADBUTILS", True)
        with pytest.raises(RuntimeError, match="Unable to get connected"):
            await get_connected_devices()


class TestAgentFromAdbDevice:
    async def test_picks_first_online_device(self, monkeypatch):
        from pymidscene.android.device import AndroidDevice

        monkeypatch.setattr(android_utils, "_HAS_ADBUTILS", True)

        fake_devices = [
            ConnectedDevice(udid="offline-1", state="offline"),
            ConnectedDevice(udid="live-1", state="device"),
        ]
        monkeypatch.setattr(
            android_utils, "_list_devices_sync", lambda: fake_devices
        )

        connect_calls: list[str] = []

        async def fake_connect(self):
            connect_calls.append(self.device_id)

        monkeypatch.setattr(AndroidDevice, "connect", fake_connect)

        # 底层 Agent 初始化要读环境变量 / 建报告目录, 我们用浅 monkey 绕过
        from pymidscene.android import agent as agent_mod

        class StubAgent:
            def __init__(self, device, **kwargs):
                self.device = device
                self.kwargs = kwargs

        monkeypatch.setattr(agent_mod, "AndroidAgent", StubAgent)

        agent = await android_utils.agent_from_adb_device()
        # 必须跳过 offline-1, 选 live-1
        assert connect_calls == ["live-1"]
        assert agent.device.device_id == "live-1"

    async def test_raises_if_no_devices(self, monkeypatch):
        monkeypatch.setattr(android_utils, "_HAS_ADBUTILS", True)
        monkeypatch.setattr(
            android_utils, "_list_devices_sync", lambda: []
        )
        with pytest.raises(RuntimeError, match="No Android devices found"):
            await android_utils.agent_from_adb_device()
