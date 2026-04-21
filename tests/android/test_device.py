"""AndroidDevice 单元测试 (全部基于 FakeAdbDevice, 不连真机)."""

from __future__ import annotations

import base64
import pytest

from pymidscene.android.device import (
    AndroidDevice,
    AndroidDeviceOpt,
    _should_use_yadb,
    _shell_escape,
)


# ------------------------------------------------------------
# 纯函数 (同步)
# ------------------------------------------------------------

class TestHelperFunctions:
    def test_should_use_yadb_ascii(self):
        assert _should_use_yadb("hello world") is False

    def test_should_use_yadb_chinese(self):
        assert _should_use_yadb("小红书") is True

    def test_should_use_yadb_format_spec(self):
        assert _should_use_yadb("hello %d") is True

    def test_shell_escape_spaces(self):
        assert _shell_escape("hello world") == "hello%sworld"

    def test_shell_escape_quotes(self):
        assert _shell_escape('say "hi"') == 'say%s\\"hi\\"'

    def test_shell_escape_backslash(self):
        assert _shell_escape("a\\b") == "a\\\\b"


# ------------------------------------------------------------
# 构造 / 连接
# ------------------------------------------------------------

class TestConstruction:
    def test_requires_device_id(self):
        with pytest.raises(ValueError):
            AndroidDevice("")

    def test_default_mapping_merged(self):
        dev = AndroidDevice(
            "s1",
            AndroidDeviceOpt(app_name_mapping={"MyApp": "com.my.app"}),
        )
        # 自定义的 + 默认的 都在
        assert "MyApp" in dev._app_name_mapping
        assert "小红书" in dev._app_name_mapping
        assert dev._app_name_mapping["MyApp"] == "com.my.app"

    def test_set_app_name_mapping_replaces(self):
        dev = AndroidDevice("s1")
        dev.set_app_name_mapping({"Only": "com.only"})
        assert dev._app_name_mapping == {"Only": "com.only"}

    @pytest.mark.asyncio
    async def test_require_device_before_connect(self):
        dev = AndroidDevice("s1")
        with pytest.raises(RuntimeError, match="not connected"):
            await dev.shell("wm size")


# ------------------------------------------------------------
# 截图 / 尺寸 / 方向
# ------------------------------------------------------------

@pytest.mark.asyncio
class TestScreenshotAndSize:
    async def test_screenshot_returns_base64_png(self, android_device):
        await android_device.connect()
        shot = await android_device.screenshot()
        assert isinstance(shot, str)
        raw = base64.b64decode(shot)
        # PNG magic number
        assert raw[:8] == b"\x89PNG\r\n\x1a\n"

    async def test_get_size_portrait(self, android_device, fake_adb_device):
        fake_adb_device.on_shell(r"^wm size$", "Physical size: 1080x2400\n")
        fake_adb_device.on_shell(r"^wm density$", "Physical density: 420\n")
        fake_adb_device.on_shell(r"dumpsys.*input", "  SurfaceOrientation: 0\n")
        await android_device.connect()
        size = await android_device.get_size()
        # density 420 → dpr 2.625, scale 1/2.625 = 0.381
        assert size["dpr"] == pytest.approx(2.625)
        assert abs(size["width"] - round(1080 / 2.625)) <= 1
        assert abs(size["height"] - round(2400 / 2.625)) <= 1

    async def test_get_size_landscape_swaps(
        self, android_device, fake_adb_device
    ):
        fake_adb_device.on_shell(r"^wm size$", "Physical size: 1080x2400\n")
        fake_adb_device.on_shell(r"^wm density$", "Physical density: 160\n")
        # orientation 1 = landscape
        fake_adb_device.on_shell(r"dumpsys.*input", "  SurfaceOrientation: 1\n")
        await android_device.connect()
        size = await android_device.get_size()
        assert size["width"] == 2400  # 横屏交换宽高
        assert size["height"] == 1080

    async def test_get_size_with_explicit_scale(self, fake_adb_device, monkeypatch):
        dev = AndroidDevice(
            "s1",
            AndroidDeviceOpt(
                screenshot_resize_scale=0.5,
                min_screenshot_buffer_size=0,
            ),
        )
        monkeypatch.setattr(
            AndroidDevice,
            "_connect_sync",
            lambda self: setattr(self, "_adb_device", fake_adb_device),
        )
        await dev.connect()
        size = await dev.get_size()
        assert size["width"] == 540
        assert size["height"] == 1200


# ------------------------------------------------------------
# 指针操作: tap/swipe/long press
# ------------------------------------------------------------

@pytest.mark.asyncio
class TestPointerOps:
    async def test_click_issues_swipe(self, android_device, fake_adb_device):
        await android_device.connect()
        await android_device.click(100, 200)
        shell_cmds = fake_adb_device.shell_calls
        swipe = [c for c in shell_cmds if "input swipe" in c][-1]
        # 点击以 0 距离 swipe 实现
        parts = swipe.split()
        assert parts[0] == "input" and parts[1] == "swipe"
        assert parts[2] == parts[4]  # from_x == to_x
        assert parts[3] == parts[5]  # from_y == to_y
        assert parts[6] == "150"     # duration

    async def test_long_press_uses_duration(self, android_device, fake_adb_device):
        await android_device.connect()
        await android_device.long_press(50, 60, duration=1500)
        swipe = [c for c in fake_adb_device.shell_calls if "input swipe" in c][-1]
        assert swipe.endswith(" 1500")

    async def test_double_click_taps_twice(self, android_device, fake_adb_device):
        await android_device.connect()
        await android_device.double_click(10, 20)
        taps = [c for c in fake_adb_device.shell_calls if "input tap" in c]
        assert len(taps) == 2

    async def test_mouse_drag_uses_adjusted_coords(
        self, android_device, fake_adb_device
    ):
        await android_device.connect()
        await android_device.mouse_drag((0, 0), (100, 200), duration=500)
        swipe = [c for c in fake_adb_device.shell_calls if "input swipe" in c][-1]
        assert swipe.endswith(" 500")

    async def test_hover_is_noop(self, android_device):
        await android_device.connect()
        # 不应抛出, 无副作用
        await android_device.hover(1, 2)


# ------------------------------------------------------------
# 滚动
# ------------------------------------------------------------

@pytest.mark.asyncio
class TestScrolling:
    @pytest.mark.parametrize("direction", ["up", "down", "left", "right"])
    async def test_scroll_direction(
        self, android_device, fake_adb_device, direction
    ):
        await android_device.connect()
        await android_device.scroll(direction, 300)
        swipes = [c for c in fake_adb_device.shell_calls if "input swipe" in c]
        assert swipes, f"expected swipe for direction={direction}"

    async def test_scroll_zero_raises(self, android_device):
        await android_device.connect()
        # 公共接口 scroll 不允许 direction 外的值
        with pytest.raises(ValueError):
            await android_device.scroll("diagonal", 10)

    async def test_scroll_until_top_loops(self, android_device, fake_adb_device):
        await android_device.connect()
        await android_device.scroll_until_top()
        swipes = [c for c in fake_adb_device.shell_calls if "input swipe" in c]
        # 与 JS 默认值对齐: 10 次
        assert len(swipes) == 10

    async def test_pull_down_swipes_downward(
        self, android_device, fake_adb_device
    ):
        await android_device.connect()
        await android_device.pull_down()
        swipe = [c for c in fake_adb_device.shell_calls if "input swipe" in c][-1]
        parts = swipe.split()
        # y_from < y_to (下拉)
        assert int(parts[3]) < int(parts[5])

    async def test_pull_up_swipes_upward(
        self, android_device, fake_adb_device
    ):
        await android_device.connect()
        await android_device.pull_up()
        swipe = [c for c in fake_adb_device.shell_calls if "input swipe" in c][-1]
        parts = swipe.split()
        assert int(parts[3]) > int(parts[5])


# ------------------------------------------------------------
# 键盘与输入
# ------------------------------------------------------------

@pytest.mark.asyncio
class TestKeyboardAndInput:
    async def test_key_press_enter(self, android_device, fake_adb_device):
        await android_device.connect()
        await android_device.key_press("Enter")
        assert any("keyevent 66" in c for c in fake_adb_device.shell_calls)

    async def test_key_press_esc_alias(self, android_device, fake_adb_device):
        await android_device.connect()
        await android_device.key_press("esc")
        assert any("keyevent 111" in c for c in fake_adb_device.shell_calls)

    async def test_input_text_ascii_uses_input_text(
        self, android_device, fake_adb_device
    ):
        await android_device.connect()
        await android_device.keyboard_type("hello world")
        has_input_text = any(
            "input text" in c and "hello%sworld" in c
            for c in fake_adb_device.shell_calls
        )
        assert has_input_text, fake_adb_device.shell_calls

    async def test_input_text_non_ascii_tries_adb_keyboard(
        self, android_device, fake_adb_device
    ):
        # ADB 广播返回正常完成字样 → 走 ADBKeyboard 路径
        fake_adb_device.on_shell(
            r"am broadcast -a ADB_INPUT_TEXT",
            "Broadcasting: Intent ...\nBroadcast completed: result=-1",
        )
        await android_device.connect()
        await android_device.keyboard_type("小红书")
        am_calls = [
            c for c in fake_adb_device.shell_calls if "am broadcast" in c
        ]
        assert am_calls, "expected an ADBKeyboard broadcast"
        assert "小红书" in am_calls[0]

    async def test_input_text_clear_first_deletes(
        self, android_device, fake_adb_device
    ):
        await android_device.connect()
        await android_device.input_text("abc", x=10, y=20, clear_first=True)
        joined = " | ".join(fake_adb_device.shell_calls)
        # 先 tap, 再 move_end (123), 再批量 del (67), 再 input text
        assert "keyevent 123" in joined
        assert "keyevent 67" in joined
        assert "input text" in joined

    async def test_clear_input_standalone(
        self, android_device, fake_adb_device
    ):
        await android_device.connect()
        await android_device.clear_input()
        joined = " | ".join(fake_adb_device.shell_calls)
        assert "keyevent 123" in joined
        assert "keyevent 67" in joined


# ------------------------------------------------------------
# Android 专属: back / home / recent / launch / run_adb_shell
# ------------------------------------------------------------

@pytest.mark.asyncio
class TestAndroidSpecific:
    async def test_back_home_recent(self, android_device, fake_adb_device):
        await android_device.connect()
        await android_device.back()
        await android_device.home()
        await android_device.recent_apps()
        calls = " | ".join(fake_adb_device.shell_calls)
        assert "keyevent 4" in calls
        assert "keyevent 3" in calls
        assert "keyevent 187" in calls

    async def test_launch_url_uses_view_intent(
        self, android_device, fake_adb_device
    ):
        await android_device.connect()
        await android_device.launch("https://example.com")
        am = [c for c in fake_adb_device.shell_calls if "am start" in c][-1]
        assert "-a android.intent.action.VIEW" in am
        assert "https://example.com" in am

    async def test_launch_package_activity(
        self, android_device, fake_adb_device
    ):
        await android_device.connect()
        await android_device.launch("com.android.settings/.Settings")
        am = [c for c in fake_adb_device.shell_calls if "am start" in c][-1]
        assert "-n com.android.settings/.Settings" in am

    async def test_launch_package_name_maps_chinese(
        self, android_device, fake_adb_device
    ):
        await android_device.connect()
        await android_device.launch("小红书")
        monkey = [c for c in fake_adb_device.shell_calls if "monkey" in c][-1]
        assert "com.xingin.xhs" in monkey

    async def test_launch_unknown_uses_raw_name(
        self, android_device, fake_adb_device
    ):
        await android_device.connect()
        await android_device.launch("com.unknown.app")
        monkey = [c for c in fake_adb_device.shell_calls if "monkey" in c][-1]
        assert "com.unknown.app" in monkey

    async def test_launch_empty_raises(self, android_device):
        await android_device.connect()
        with pytest.raises(ValueError):
            await android_device.launch("")

    async def test_run_adb_shell_requires_command(self, android_device):
        await android_device.connect()
        with pytest.raises(ValueError):
            await android_device.run_adb_shell("   ")

    async def test_run_adb_shell_passes_through(
        self, android_device, fake_adb_device
    ):
        fake_adb_device.on_shell(r"getprop", "pocketprop")
        await android_device.connect()
        result = await android_device.run_adb_shell("getprop ro.build.version.sdk")
        assert result == "pocketprop"


# ------------------------------------------------------------
# evaluate_javascript 的 Android 转译
# ------------------------------------------------------------

@pytest.mark.asyncio
class TestEvaluateJavaScript:
    async def test_window_scroll_to_top(self, android_device, fake_adb_device):
        await android_device.connect()
        await android_device.evaluate_javascript("window.scrollTo(0, 0)")
        swipes = [c for c in fake_adb_device.shell_calls if "input swipe" in c]
        assert len(swipes) == 10  # scroll_until_top 循环 10 次

    async def test_window_scroll_to_bottom(
        self, android_device, fake_adb_device
    ):
        await android_device.connect()
        await android_device.evaluate_javascript(
            "window.scrollTo(0, document.body.scrollHeight)"
        )
        swipes = [c for c in fake_adb_device.shell_calls if "input swipe" in c]
        assert len(swipes) == 10

    async def test_history_back(self, android_device, fake_adb_device):
        await android_device.connect()
        await android_device.evaluate_javascript("window.history.back()")
        assert any("keyevent 4" in c for c in fake_adb_device.shell_calls)

    async def test_unknown_script_is_noop(
        self, android_device, fake_adb_device
    ):
        await android_device.connect()
        pre = len(fake_adb_device.shell_calls)
        await android_device.evaluate_javascript("console.log('hi')")
        assert len(fake_adb_device.shell_calls) == pre


# ------------------------------------------------------------
# Web 接口的 Android no-op 行为
# ------------------------------------------------------------

@pytest.mark.asyncio
class TestWebNoops:
    async def test_wait_for_navigation_no_raise(self, android_device):
        await android_device.connect()
        await android_device.wait_for_navigation(100)

    async def test_wait_for_network_idle_no_raise(self, android_device):
        await android_device.connect()
        await android_device.wait_for_network_idle(100)

    async def test_get_element_xpath_returns_none(self, android_device):
        await android_device.connect()
        xp = await android_device.get_element_xpath(10, 20)
        assert xp is None


# ------------------------------------------------------------
# get_ui_context
# ------------------------------------------------------------

@pytest.mark.asyncio
class TestUIContext:
    async def test_returns_screenshot_and_size(self, android_device):
        await android_device.connect()
        ctx = await android_device.get_ui_context()
        assert ctx.screenshot is not None
        assert ctx.size["width"] > 0 and ctx.size["height"] > 0
