"""
共享 fixture: 伪造 WDA 后端的 httpx MockTransport.

所有 iOS 测试都基于此, 不需要真实设备/WDA.
"""

from __future__ import annotations

import base64
import io
import json
import re
from typing import Any, Callable, Optional

import httpx
import pytest
import pytest_asyncio
from PIL import Image

from pymidscene.ios.device import IOSDevice, IOSDeviceOpt
from pymidscene.ios.webdriver_client import IOSWebDriverClient


class FakeWDA:
    """
    伪 WDA 后端. 用法::

        wda.on("POST", r"/session$", responder)

    默认注册了创建 session / status / window/rect / screenshot / screen 等常用路径,
    测试用例可以再 `on(...)` 覆盖.
    """

    def __init__(self) -> None:
        self.session_id = "test-session-1"
        self.requests: list[tuple[str, str, Any]] = []
        self._handlers: list[
            tuple[str, re.Pattern[str], Callable[[httpx.Request], httpx.Response]]
        ] = []
        self._register_defaults()

    def _register_defaults(self) -> None:
        # 创建 session
        self.on(
            "POST",
            r"^/session$",
            lambda req: httpx.Response(
                200,
                json={"sessionId": self.session_id, "value": {}},
            ),
        )
        # appium settings (post-setup)
        self.on(
            "POST",
            r"^/session/[^/]+/appium/settings$",
            lambda req: httpx.Response(200, json={"value": None}),
        )
        # delete session
        self.on(
            "DELETE",
            r"^/session/[^/]+$",
            lambda req: httpx.Response(200, json={"value": None}),
        )
        # status (device info)
        self.on(
            "GET",
            r"^/status$",
            lambda req: httpx.Response(
                200,
                json={
                    "value": {
                        "device": {
                            "udid": "FAKE-UDID-123",
                            "name": "FakePhone",
                            "model": "iPhone 15",
                        }
                    }
                },
            ),
        )
        # window rect (新协议)
        self.on(
            "GET",
            r"^/session/[^/]+/window/rect$",
            lambda req: httpx.Response(
                200,
                json={"value": {"x": 0, "y": 0, "width": 390, "height": 844}},
            ),
        )
        # screen scale
        self.on(
            "GET",
            r"^/session/[^/]+/wda/screen$",
            lambda req: httpx.Response(
                200, json={"value": {"scale": 3.0, "statusBarSize": {"width": 390, "height": 44}}}
            ),
        )
        # screenshot
        img = Image.new("RGB", (100, 200), color=(10, 20, 30))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        png_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        self.on(
            "GET",
            r"^/session/[^/]+/screenshot$",
            lambda req: httpx.Response(200, json={"value": png_b64}),
        )
        # 通用: 成功
        self.on(
            "POST",
            r"^/session/[^/]+/wda/(tap|doubleTap|tapWithNumberOfTaps|touchAndHold|keys|keyboard/dismiss|pressButton|apps/(launch|activate|terminate))$",
            lambda req: httpx.Response(200, json={"value": None}),
        )
        self.on(
            "POST",
            r"^/session/[^/]+/url$",
            lambda req: httpx.Response(200, json={"value": None}),
        )
        self.on(
            "POST",
            r"^/session/[^/]+/actions$",
            lambda req: httpx.Response(200, json={"value": None}),
        )
        # 获取 active element (默认无)
        self.on(
            "GET",
            r"^/session/[^/]+/element/active$",
            lambda req: httpx.Response(
                200, json={"value": None}
            ),
        )
        # clear element
        self.on(
            "POST",
            r"^/session/[^/]+/element/[^/]+/clear$",
            lambda req: httpx.Response(200, json={"value": None}),
        )

    def on(
        self,
        method: str,
        pattern: str,
        responder: Callable[[httpx.Request], httpx.Response],
    ) -> None:
        """注册请求处理器. 后注册的优先级高于先注册的."""
        self._handlers.insert(0, (method.upper(), re.compile(pattern), responder))

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        method = request.method.upper()
        body: Any = None
        if request.content:
            try:
                body = json.loads(request.content)
            except Exception:
                body = request.content
        self.requests.append((method, path, body))
        for hm, hp, hh in self._handlers:
            if method == hm and hp.search(path):
                return hh(request)
        return httpx.Response(
            404, json={"value": {"error": "unhandled", "message": f"{method} {path}"}}
        )

    def calls_for(self, method: str, path_substr: str) -> list[tuple[str, str, Any]]:
        method = method.upper()
        return [c for c in self.requests if c[0] == method and path_substr in c[1]]


@pytest.fixture
def fake_wda() -> FakeWDA:
    return FakeWDA()


@pytest.fixture
def wda_transport(fake_wda: FakeWDA) -> httpx.MockTransport:
    return httpx.MockTransport(fake_wda.handle)


@pytest.fixture
def ios_client(wda_transport) -> IOSWebDriverClient:
    return IOSWebDriverClient(host="fake", port=0, transport=wda_transport)


@pytest_asyncio.fixture
async def connected_ios_client(
    ios_client: IOSWebDriverClient,
) -> IOSWebDriverClient:
    await ios_client.create_session()
    try:
        yield ios_client
    finally:
        await ios_client.aclose()


@pytest_asyncio.fixture
async def ios_device(wda_transport) -> IOSDevice:
    """已连接的 IOSDevice (mock WDA)."""
    client = IOSWebDriverClient(host="fake", port=0, transport=wda_transport)
    device = IOSDevice(
        options=IOSDeviceOpt(auto_dismiss_keyboard=False),
        client=client,
    )
    await device.connect()
    try:
        yield device
    finally:
        await device.destroy()
