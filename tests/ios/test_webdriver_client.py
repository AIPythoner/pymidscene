"""IOSWebDriverClient 的 HTTP 行为测试 (MockTransport)."""

from __future__ import annotations

import base64
import io

import httpx
import pytest
from PIL import Image

from pymidscene.ios.webdriver_client import IOSWebDriverClient
from pymidscene.webdriver.client import WebDriverError


pytestmark = pytest.mark.asyncio


class TestSession:
    async def test_create_session_posts_capabilities(
        self, ios_client, fake_wda
    ):
        sess = await ios_client.create_session({"foo": "bar"})
        assert sess["sessionId"] == fake_wda.session_id

        session_calls = fake_wda.calls_for("POST", "/session")
        # 至少有一次 POST /session 带 capabilities
        initial = [c for c in session_calls if c[1] == "/session"]
        assert initial
        body = initial[0][2]
        assert "capabilities" in body
        merged = body["capabilities"]["alwaysMatch"]
        assert merged.get("platformName") == "iOS"
        assert merged.get("foo") == "bar"

    async def test_delete_session_resets_id(
        self, connected_ios_client, fake_wda
    ):
        await connected_ios_client.delete_session()
        assert connected_ios_client.session_id is None
        assert fake_wda.calls_for("DELETE", "/session/")

    async def test_ensure_session_without_connect_raises(self, ios_client):
        with pytest.raises(WebDriverError):
            await ios_client.take_screenshot()


class TestScreenAndSize:
    async def test_take_screenshot_returns_base64(self, connected_ios_client):
        b64 = await connected_ios_client.take_screenshot()
        raw = base64.b64decode(b64)
        assert raw[:8] == b"\x89PNG\r\n\x1a\n"

    async def test_get_window_size(self, connected_ios_client):
        size = await connected_ios_client.get_window_size()
        assert size == {"width": 390, "height": 844}

    async def test_get_window_size_falls_back(
        self, connected_ios_client, fake_wda
    ):
        # rect 失败 → 回退 /window/size
        fake_wda.on(
            "GET",
            r"^/session/[^/]+/window/rect$",
            lambda req: httpx.Response(
                500, json={"value": {"error": "unsupported"}}
            ),
        )
        fake_wda.on(
            "GET",
            r"^/session/[^/]+/window/size$",
            lambda req: httpx.Response(
                200, json={"value": {"width": 320, "height": 568}}
            ),
        )
        size = await connected_ios_client.get_window_size()
        assert size == {"width": 320, "height": 568}

    async def test_get_screen_scale_from_wda(self, connected_ios_client):
        scale = await connected_ios_client.get_screen_scale()
        assert scale == 3.0

    async def test_get_screen_scale_fallback_calc(
        self, connected_ios_client, fake_wda
    ):
        # /wda/screen 不可用 → 用 screenshot 尺寸与 window size 计算
        fake_wda.on(
            "GET",
            r"^/session/[^/]+/wda/screen$",
            lambda req: httpx.Response(
                404, json={"value": {"error": "nope"}}
            ),
        )
        # screenshot 400x800, window 200x400 → scale = 2
        img = Image.new("RGB", (400, 800), color=(0, 0, 0))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        fake_wda.on(
            "GET",
            r"^/session/[^/]+/screenshot$",
            lambda req: httpx.Response(200, json={"value": b64}),
        )
        fake_wda.on(
            "GET",
            r"^/session/[^/]+/window/rect$",
            lambda req: httpx.Response(
                200, json={"value": {"width": 200, "height": 400}}
            ),
        )
        scale = await connected_ios_client.get_screen_scale()
        assert scale == 2


class TestTouch:
    async def test_tap_new_endpoint(self, connected_ios_client, fake_wda):
        await connected_ios_client.tap(100, 200)
        call = fake_wda.calls_for("POST", "/wda/tap")[-1]
        assert call[2] == {"x": 100, "y": 200}

    async def test_tap_falls_back_to_legacy(
        self, connected_ios_client, fake_wda
    ):
        # 先注册失败的新端点
        fake_wda.on(
            "POST",
            r"^/session/[^/]+/wda/tap$",
            lambda req: httpx.Response(
                500, json={"value": {"error": "gone"}}
            ),
        )
        fake_wda.on(
            "POST",
            r"^/session/[^/]+/wda/tap/0$",
            lambda req: httpx.Response(200, json={"value": None}),
        )
        await connected_ios_client.tap(50, 60)
        legacy = fake_wda.calls_for("POST", "/wda/tap/0")
        assert legacy

    async def test_double_tap(self, connected_ios_client, fake_wda):
        await connected_ios_client.double_tap(10, 20)
        assert fake_wda.calls_for("POST", "/wda/doubleTap")

    async def test_triple_tap(self, connected_ios_client, fake_wda):
        await connected_ios_client.triple_tap(10, 20)
        c = fake_wda.calls_for("POST", "/wda/tapWithNumberOfTaps")[-1]
        assert c[2]["numberOfTaps"] == 3

    async def test_long_press_converts_ms_to_s(
        self, connected_ios_client, fake_wda
    ):
        await connected_ios_client.long_press(10, 20, duration_ms=1500)
        c = fake_wda.calls_for("POST", "/wda/touchAndHold")[-1]
        assert c[2]["duration"] == pytest.approx(1.5)

    async def test_swipe_uses_w3c_actions(
        self, connected_ios_client, fake_wda
    ):
        await connected_ios_client.swipe(1, 2, 3, 4, duration_ms=200)
        c = fake_wda.calls_for("POST", "/actions")[-1]
        actions = c[2]["actions"][0]["actions"]
        moves = [a for a in actions if a["type"] == "pointerMove"]
        assert moves[0]["x"] == 1 and moves[0]["y"] == 2
        assert moves[1]["x"] == 3 and moves[1]["y"] == 4
        assert moves[1]["duration"] == 200


class TestKeyboard:
    async def test_type_text_splits_into_chars(
        self, connected_ios_client, fake_wda
    ):
        await connected_ios_client.type_text("hi")
        c = fake_wda.calls_for("POST", "/wda/keys")[-1]
        assert c[2]["value"] == ["h", "i"]

    async def test_press_key_enter(self, connected_ios_client, fake_wda):
        await connected_ios_client.press_key("Enter")
        c = fake_wda.calls_for("POST", "/wda/keys")[-1]
        assert c[2]["value"] == ["\n"]

    async def test_press_key_arrow(self, connected_ios_client, fake_wda):
        await connected_ios_client.press_key("ArrowLeft")
        c = fake_wda.calls_for("POST", "/wda/keys")[-1]
        assert c[2]["value"] == ["\uE012"]

    async def test_press_key_single_char(self, connected_ios_client, fake_wda):
        await connected_ios_client.press_key("a")
        c = fake_wda.calls_for("POST", "/wda/keys")[-1]
        assert c[2]["value"] == ["a"]

    async def test_press_key_unsupported_raises(
        self, connected_ios_client, fake_wda
    ):
        with pytest.raises(WebDriverError):
            await connected_ios_client.press_key("UnknownComplexKey")

    async def test_dismiss_keyboard_ok(self, connected_ios_client, fake_wda):
        ok = await connected_ios_client.dismiss_keyboard()
        assert ok is True
        c = fake_wda.calls_for("POST", "/wda/keyboard/dismiss")[-1]
        assert c[2] == {"keyNames": ["done"]}


class TestAppAndUrl:
    async def test_launch_app(self, connected_ios_client, fake_wda):
        await connected_ios_client.launch_app("com.apple.mobilesafari")
        c = fake_wda.calls_for("POST", "/wda/apps/launch")[-1]
        assert c[2] == {"bundleId": "com.apple.mobilesafari"}

    async def test_activate_terminate(self, connected_ios_client, fake_wda):
        await connected_ios_client.activate_app("com.foo")
        await connected_ios_client.terminate_app("com.foo")
        assert fake_wda.calls_for("POST", "/wda/apps/activate")
        assert fake_wda.calls_for("POST", "/wda/apps/terminate")

    async def test_open_url(self, connected_ios_client, fake_wda):
        await connected_ios_client.open_url("https://example.com")
        c = fake_wda.calls_for("POST", "/url")[-1]
        assert c[2] == {"url": "https://example.com"}

    async def test_press_home_button(self, connected_ios_client, fake_wda):
        await connected_ios_client.press_home_button()
        c = fake_wda.calls_for("POST", "/wda/pressButton")[-1]
        assert c[2] == {"name": "home"}

    async def test_app_switcher_swipes_up(
        self, connected_ios_client, fake_wda
    ):
        await connected_ios_client.app_switcher()
        assert fake_wda.calls_for("POST", "/actions")


class TestActiveElement:
    async def test_get_active_element_legacy(
        self, connected_ios_client, fake_wda
    ):
        fake_wda.on(
            "GET",
            r"^/session/[^/]+/element/active$",
            lambda req: httpx.Response(
                200, json={"value": {"ELEMENT": "abc-123"}}
            ),
        )
        assert await connected_ios_client.get_active_element() == "abc-123"

    async def test_get_active_element_w3c(
        self, connected_ios_client, fake_wda
    ):
        key = "element-6066-11e4-a52e-4f735466cecf"
        fake_wda.on(
            "GET",
            r"^/session/[^/]+/element/active$",
            lambda req: httpx.Response(
                200, json={"value": {key: "xyz-789"}}
            ),
        )
        assert await connected_ios_client.get_active_element() == "xyz-789"

    async def test_clear_active_element(
        self, connected_ios_client, fake_wda
    ):
        fake_wda.on(
            "GET",
            r"^/session/[^/]+/element/active$",
            lambda req: httpx.Response(
                200, json={"value": {"ELEMENT": "id-1"}}
            ),
        )
        assert await connected_ios_client.clear_active_element() is True
        assert fake_wda.calls_for("POST", "/element/id-1/clear")

    async def test_clear_active_element_none(self, connected_ios_client):
        assert await connected_ios_client.clear_active_element() is False


class TestDeviceInfo:
    async def test_get_device_info(self, connected_ios_client):
        info = await connected_ios_client.get_device_info()
        assert info == {
            "udid": "FAKE-UDID-123",
            "name": "FakePhone",
            "model": "iPhone 15",
        }


class TestExecuteRequest:
    async def test_execute_request_passes_through(
        self, connected_ios_client, fake_wda
    ):
        fake_wda.on(
            "GET",
            r"^/status$",
            lambda req: httpx.Response(200, json={"value": {"ok": True}}),
        )
        result = await connected_ios_client.execute_request("GET", "/status")
        assert isinstance(result, dict)
