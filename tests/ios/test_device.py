"""IOSDevice 层单元测试."""

from __future__ import annotations

import base64

import httpx
import pytest

from pymidscene.ios.device import (
    IOSDevice,
    IOSDeviceOpt,
    _screenshots_similar,
)


# ------------------------------------------------------------
# 纯函数
# ------------------------------------------------------------

class TestScreenshotCompare:
    def test_identical(self):
        assert _screenshots_similar("x" * 100, "x" * 100, 1) is True

    def test_length_diff_too_big(self):
        assert _screenshots_similar("x" * 100, "x" * 300, 50) is False

    def test_within_tolerance(self):
        a = "x" * 2000
        b = "y" + "x" * 1999  # 0.05% diff
        assert _screenshots_similar(a, b, 1) is True

    def test_outside_tolerance(self):
        a = "x" * 2000
        b = "y" * 2000
        assert _screenshots_similar(a, b, 1) is False


class TestConstruction:
    def test_default_mapping_merged(self):
        d = IOSDevice(
            IOSDeviceOpt(app_name_mapping={"MyApp": "com.my.app"})
        )
        assert "MyApp" in d._app_name_mapping
        assert "微信" in d._app_name_mapping

    def test_custom_wda_url(self):
        d = IOSDevice(IOSDeviceOpt(wda_host="h", wda_port=1234))
        assert d.wda.base_url == "http://h:1234"

    def test_base_url_override(self):
        d = IOSDevice(
            IOSDeviceOpt(wda_base_url="http://10.0.0.1:8100/wda")
        )
        assert d.wda.base_url == "http://10.0.0.1:8100/wda"


# ------------------------------------------------------------
# 异步交互
# ------------------------------------------------------------

@pytest.mark.asyncio
class TestLifecycle:
    async def test_connect_populates_device_id(self, ios_device):
        # fake WDA /status 返回 FAKE-UDID-123
        assert ios_device.device_id == "FAKE-UDID-123"
        assert "FAKE-UDID-123" in ios_device.describe()

    async def test_connect_is_idempotent(self, ios_device, fake_wda):
        sessions = fake_wda.calls_for("POST", "/session")
        # 再 connect 一次
        await ios_device.connect()
        sessions_after = fake_wda.calls_for("POST", "/session")
        # 只有 /session 根路径的 POST 才算新 session
        init_count = sum(1 for c in sessions if c[1] == "/session")
        init_count_after = sum(
            1 for c in sessions_after if c[1] == "/session"
        )
        assert init_count == init_count_after == 1


@pytest.mark.asyncio
class TestScreenAndSize:
    async def test_screenshot(self, ios_device):
        b64 = await ios_device.screenshot()
        raw = base64.b64decode(b64)
        assert raw[:8] == b"\x89PNG\r\n\x1a\n"

    async def test_get_size(self, ios_device):
        size = await ios_device.get_size()
        assert size["width"] == 390
        assert size["height"] == 844
        assert size["dpr"] == 3.0


@pytest.mark.asyncio
class TestPointerOps:
    async def test_click_hits_wda_tap(self, ios_device, fake_wda):
        await ios_device.click(12.4, 56.7)
        c = fake_wda.calls_for("POST", "/wda/tap")[-1]
        assert c[2] == {"x": 12, "y": 57}  # round

    async def test_double_click(self, ios_device, fake_wda):
        await ios_device.double_click(1, 2)
        assert fake_wda.calls_for("POST", "/wda/doubleTap")

    async def test_long_press_default_duration(self, ios_device, fake_wda):
        await ios_device.long_press(1, 2)
        c = fake_wda.calls_for("POST", "/wda/touchAndHold")[-1]
        assert c[2]["duration"] == pytest.approx(1.0)

    async def test_hover_is_noop(self, ios_device):
        await ios_device.hover(1, 2)

    async def test_swipe(self, ios_device, fake_wda):
        await ios_device.swipe(0, 0, 10, 10)
        assert fake_wda.calls_for("POST", "/actions")

    async def test_drag_and_drop(self, ios_device, fake_wda):
        await ios_device.drag_and_drop((0, 0), (20, 20))
        assert fake_wda.calls_for("POST", "/actions")


@pytest.mark.asyncio
class TestScroll:
    @pytest.mark.parametrize(
        "direction", ["up", "down", "left", "right"]
    )
    async def test_single_scroll_direction(
        self, ios_device, fake_wda, direction
    ):
        await ios_device.scroll(direction, 200)
        assert fake_wda.calls_for("POST", "/actions")

    async def test_scroll_bad_direction(self, ios_device):
        with pytest.raises(ValueError):
            await ios_device.scroll("diagonal", 10)


@pytest.mark.asyncio
class TestKeyboardInput:
    async def test_input_text_with_xy(self, ios_device, fake_wda):
        await ios_device.input_text("hi", x=1, y=2)
        # tap 然后 keys
        tap_calls = fake_wda.calls_for("POST", "/wda/tap")
        keys_calls = fake_wda.calls_for("POST", "/wda/keys")
        assert tap_calls and keys_calls
        assert keys_calls[-1][2]["value"] == ["h", "i"]

    async def test_input_text_clear_first_calls_clear(
        self, ios_device, fake_wda
    ):
        # 安排 /element/active 返回一个元素
        fake_wda.on(
            "GET",
            r"^/session/[^/]+/element/active$",
            lambda req: httpx.Response(
                200, json={"value": {"ELEMENT": "el-1"}}
            ),
        )
        await ios_device.input_text("new", x=1, y=2, clear_first=True)
        # 清空过该元素
        assert fake_wda.calls_for("POST", "/element/el-1/clear")

    async def test_key_press_forwards(self, ios_device, fake_wda):
        await ios_device.key_press("Enter")
        c = fake_wda.calls_for("POST", "/wda/keys")[-1]
        assert c[2]["value"] == ["\n"]

    async def test_hide_keyboard_ok(self, ios_device, fake_wda):
        ok = await ios_device.hide_keyboard()
        assert ok is True
        assert fake_wda.calls_for("POST", "/wda/keyboard/dismiss")


@pytest.mark.asyncio
class TestIOSSpecific:
    async def test_launch_url(self, ios_device, fake_wda):
        await ios_device.launch("https://example.com")
        c = fake_wda.calls_for("POST", "/url")[-1]
        assert c[2] == {"url": "https://example.com"}

    async def test_launch_bundle_id(self, ios_device, fake_wda):
        await ios_device.launch("com.apple.mobilesafari")
        c = fake_wda.calls_for("POST", "/wda/apps/launch")[-1]
        assert c[2]["bundleId"] == "com.apple.mobilesafari"

    async def test_launch_chinese_maps_to_bundle(
        self, ios_device, fake_wda
    ):
        await ios_device.launch("微信")
        c = fake_wda.calls_for("POST", "/wda/apps/launch")[-1]
        assert c[2]["bundleId"] == "com.tencent.xin"

    async def test_launch_empty_raises(self, ios_device):
        with pytest.raises(ValueError):
            await ios_device.launch("")

    async def test_home(self, ios_device, fake_wda):
        await ios_device.home()
        c = fake_wda.calls_for("POST", "/wda/pressButton")[-1]
        assert c[2] == {"name": "home"}

    async def test_app_switcher(self, ios_device, fake_wda):
        await ios_device.app_switcher()
        assert fake_wda.calls_for("POST", "/actions")

    async def test_activate_and_terminate(self, ios_device, fake_wda):
        await ios_device.activate_app("Safari")
        await ios_device.terminate_app("Safari")
        assert fake_wda.calls_for("POST", "/wda/apps/activate")
        assert fake_wda.calls_for("POST", "/wda/apps/terminate")

    async def test_run_wda_request_passes_through(
        self, ios_device, fake_wda
    ):
        fake_wda.on(
            "GET",
            r"^/foo/bar$",
            lambda req: httpx.Response(200, json={"value": {"ok": 1}}),
        )
        out = await ios_device.run_wda_request("GET", "/foo/bar")
        assert isinstance(out, dict)

    async def test_run_wda_request_bad_method(self, ios_device):
        with pytest.raises(ValueError):
            await ios_device.run_wda_request("PATCH", "/x")


@pytest.mark.asyncio
class TestEvaluateJavaScript:
    async def test_scroll_to_top_triggers_scroll_until(
        self, ios_device, fake_wda
    ):
        # 让到顶检测立即停止 (截图始终一样)
        # 注入一个固定 screenshot, 多次一致即认为到顶
        await ios_device.evaluate_javascript("window.scrollTo(0, 0)")
        # 触发过至少一次 screenshot
        assert fake_wda.calls_for("GET", "/screenshot")

    async def test_history_back_maps_to_home(self, ios_device, fake_wda):
        await ios_device.evaluate_javascript("window.history.back()")
        assert fake_wda.calls_for("POST", "/wda/pressButton")

    async def test_unknown_is_noop(self, ios_device, fake_wda):
        pre = len(fake_wda.requests)
        await ios_device.evaluate_javascript("console.log('x')")
        assert len(fake_wda.requests) == pre


@pytest.mark.asyncio
class TestWebNoops:
    async def test_wait_for_navigation(self, ios_device):
        await ios_device.wait_for_navigation()

    async def test_wait_for_network_idle(self, ios_device):
        await ios_device.wait_for_network_idle()

    async def test_ui_context(self, ios_device):
        ctx = await ios_device.get_ui_context()
        assert ctx.screenshot is not None
        assert ctx.size["width"] > 0
