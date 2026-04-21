"""
共享 fixture: 构造带 mock adbutils 的 AndroidDevice.

所有测试都通过 FakeAdbDevice 记录 shell 调用并返回预设响应, 不连真机.
"""

from __future__ import annotations

import io
import re
from typing import Callable, Optional

import pytest
from PIL import Image

from pymidscene.android.device import AndroidDevice, AndroidDeviceOpt


class FakeSync:
    """模拟 adbutils.AdbDevice.sync 用的伪对象."""

    def __init__(self, data: bytes = b"") -> None:
        self._data = data

    def iter_content(self, _remote: str):
        yield self._data


class FakeAdbDevice:
    """替代 adbutils.AdbDevice. 记录所有 shell 调用."""

    def __init__(self, serial: str = "fake-serial") -> None:
        self.serial = serial
        self.shell_calls: list[str] = []
        self._shell_responders: list[tuple[str, Callable[[str], str]]] = []
        # prop 对象 — 连接验证用
        self.prop = type("Prop", (), {"name": "fake-device"})()
        # 默认 screenshot 图片 (15KB 的 PNG, 足以过 min_bytes 校验)
        img = Image.new("RGB", (400, 800), color=(10, 20, 30))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        png = buf.getvalue()
        # 填充到 >= 15KB
        if len(png) < 15_000:
            # 额外塞一段 noise 到 PIL 无法利用的区域 -> 直接生成更大的图
            img2 = Image.new("RGB", (800, 1600))
            # 随机化像素以扩大体积
            import random
            pixels = [(random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
                      for _ in range(800 * 1600)]
            img2.putdata(pixels)
            buf = io.BytesIO()
            img2.save(buf, format="PNG")
            png = buf.getvalue()
        self.screenshot_png = png
        self._screenshot_image = Image.open(io.BytesIO(png))
        self.sync = FakeSync(png)

    def on_shell(
        self, pattern: str, responder: Callable[[str], str] | str
    ) -> None:
        """注册匹配正则 pattern 的 shell 指令的返回值.

        后注册的优先级高于先注册的, 方便测试覆盖默认响应.
        """
        if isinstance(responder, str):
            text = responder
            responder = lambda _cmd, _t=text: _t  # noqa: E731
        self._shell_responders.insert(0, (pattern, responder))

    def shell(self, cmd: str) -> str:
        self.shell_calls.append(cmd)
        for pattern, responder in self._shell_responders:
            if re.search(pattern, cmd):
                return responder(cmd)
        return ""

    def screenshot(self, display_id: Optional[int] = None):  # noqa: ARG002
        return self._screenshot_image


@pytest.fixture
def fake_adb_device() -> FakeAdbDevice:
    """单独一台 FakeAdbDevice, 测试用例可按需 on_shell 注册响应."""
    dev = FakeAdbDevice("serial-fake")
    # 预设常用响应
    dev.on_shell(r"^wm size$", "Physical size: 1080x2400\n")
    dev.on_shell(r"^wm density$", "Physical density: 420\n")
    dev.on_shell(r"dumpsys.*input", "  SurfaceOrientation: 0\n")
    dev.on_shell(
        r"dumpsys input_method", "mInputShown=false\n"
    )
    return dev


@pytest.fixture
def android_device(
    fake_adb_device: FakeAdbDevice, monkeypatch
) -> AndroidDevice:
    """
    返回一个已连接的 AndroidDevice, 底层是 FakeAdbDevice.

    monkeypatch `_connect_sync` 绕过真正的 adbutils 连接.
    """
    device = AndroidDevice(
        device_id="serial-fake",
        options=AndroidDeviceOpt(
            min_screenshot_buffer_size=0,  # 测试图可能较小
            auto_dismiss_keyboard=False,
        ),
    )

    def _fake_connect(self):
        self._adb_device = fake_adb_device
        self._adb_client = object()

    monkeypatch.setattr(AndroidDevice, "_connect_sync", _fake_connect)
    return device
