"""
AndroidDevice - 对应 packages/android/src/device.ts

基于 `adbutils` 的 Android 设备适配器，实现 ``AbstractInterface``。

核心差异与 JS 版对齐说明：

- JS 版基于 `appium-adb`（Node.js），本实现基于 `adbutils`（Python）。API 有差异，
  但对外方法签名与语义保持一致。
- UI 树：JS 版 `getElementsInfo()` 返回空数组，本实现同样不解析 uiautomator XML，
  走纯视觉方案。`get_element_xpath` 等返回 None/False（继承默认实现）。
- 输入法：
  - ASCII 文本：`input text` via shell。
  - 非 ASCII：优先使用 ADBKeyboard（IME 策略 `adb-keyboard`）。
    用户需自行安装并设为默认 IME。策略可通过 `MIDSCENE_ANDROID_IME_STRATEGY`
    或 `AndroidDeviceOpt.ime_strategy` 配置。
- JS 版的 yadb 方案（Java payload 推送至 /data/local/tmp）暂未移植，
  通过 `ime_strategy="always-yadb"` 时会 fallback 到 `input text` 并打警告。
- 坐标系：adbutils 的 `click/swipe` 使用物理像素，本类在内部按 JS 同逻辑
  保留 `scaling_ratio` 以支持 `screenshotResizeScale`。
"""

from __future__ import annotations

import asyncio
import base64
import io
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from ..core.types import UIContext, ScreenshotItem
from ..shared.env.constants import (
    IME_STRATEGY_ADB_KEYBOARD,
    IME_STRATEGY_ALWAYS_YADB,
    IME_STRATEGY_YADB_FOR_NON_ASCII,
    MIDSCENE_ADB_PATH,
    MIDSCENE_ADB_REMOTE_HOST,
    MIDSCENE_ADB_REMOTE_PORT,
    MIDSCENE_ANDROID_IME_STRATEGY,
)
from ..shared.logger import logger
from ..shared.types import Size
from ..web_integration.base import AbstractInterface
from .app_name_mapping import DEFAULT_APP_NAME_MAPPING, resolve_package_name

# adbutils 是可选依赖；延迟 import 让未装 android extra 的用户能正常加载
# 包的其他部分（不调用 Android 功能）。
try:
    import adbutils  # type: ignore[import-not-found]
    _HAS_ADBUTILS = True
except ImportError:  # pragma: no cover - tested via monkeypatch
    adbutils = None  # type: ignore[assignment]
    _HAS_ADBUTILS = False


# 与 JS 对齐的默认值
DEFAULT_SCROLL_UNTIL_TIMES = 10
DEFAULT_FAST_SCROLL_DURATION_MS = 100
DEFAULT_NORMAL_SCROLL_DURATION_MS = 1000
DEFAULT_MIN_SCREENSHOT_BYTES = 10 * 1024  # 10 KB


@dataclass
class AndroidDeviceOpt:
    """
    AndroidDevice 可选参数 - 对齐 JS `AndroidDeviceOpt`.

    Attributes:
        android_adb_path: `adb` 可执行文件路径（为空时读取 ``MIDSCENE_ADB_PATH``）.
        remote_adb_host: 远程 adb server host（为空时读取 ``MIDSCENE_ADB_REMOTE_HOST``）.
        remote_adb_port: 远程 adb server port.
        display_id: 多屏设备上指定目标 display id.
        use_physical_display_id_for_display_lookup: 如为 True, 根据 physical
            display id 匹配 dumpsys 输出而非 displayId.
        use_physical_display_id_for_screenshot: screencap -d 使用 physical id.
        screenshot_resize_scale: 截图缩放比例 (overrides 1 / dpr).
        always_refresh_screen_info: 每次都重新查询屏幕尺寸/方向.
        min_screenshot_buffer_size: 小于该字节数认为截图无效 (默认 10KB, 0 关闭).
        auto_dismiss_keyboard: 输入完成后自动关闭软键盘.
        keyboard_dismiss_strategy: ``esc-first`` / ``back-first``.
        ime_strategy: 输入法策略.
        app_name_mapping: 额外的 app 名 → 包名映射 (优先级高于默认).
    """

    android_adb_path: Optional[str] = None
    remote_adb_host: Optional[str] = None
    remote_adb_port: Optional[int] = None
    display_id: Optional[int] = None
    use_physical_display_id_for_display_lookup: bool = False
    use_physical_display_id_for_screenshot: bool = False
    screenshot_resize_scale: Optional[float] = None
    always_refresh_screen_info: bool = False
    min_screenshot_buffer_size: int = DEFAULT_MIN_SCREENSHOT_BYTES
    auto_dismiss_keyboard: bool = True
    keyboard_dismiss_strategy: str = "esc-first"  # or "back-first"
    ime_strategy: Optional[str] = None
    app_name_mapping: dict[str, str] = field(default_factory=dict)


# ---- Web key name -> Android keyevent 码 ----
# 对齐 JS `keyboardPress` 中的 keyCodeMap.
_KEY_NAME_NORMALIZE: dict[str, str] = {
    "enter": "Enter",
    "backspace": "Backspace",
    "tab": "Tab",
    "escape": "Escape",
    "esc": "Escape",
    "home": "Home",
    "end": "End",
    "arrowup": "ArrowUp",
    "arrowdown": "ArrowDown",
    "arrowleft": "ArrowLeft",
    "arrowright": "ArrowRight",
    "up": "ArrowUp",
    "down": "ArrowDown",
    "left": "ArrowLeft",
    "right": "ArrowRight",
    "space": "Space",
    "delete": "Delete",
    "del": "Delete",
}

_KEY_CODE_MAP: dict[str, int] = {
    "Enter": 66,
    "Backspace": 67,
    "Tab": 61,
    "ArrowUp": 19,
    "ArrowDown": 20,
    "ArrowLeft": 21,
    "ArrowRight": 22,
    "Escape": 111,
    "Home": 3,
    "End": 123,
    "Space": 62,
    "Delete": 112,
}


_NON_ASCII_RE = re.compile(r"[\x80-\uffff]")
_FORMAT_SPEC_RE = re.compile(r"%[a-zA-Z]")


def _should_use_yadb(text: str) -> bool:
    """对齐 JS `shouldUseYadbForText`."""
    return bool(_NON_ASCII_RE.search(text) or _FORMAT_SPEC_RE.search(text))


def _shell_escape(text: str) -> str:
    """
    为 `adb shell input text "..."` 做最小必要转义.

    Android `input text` 在接到 shell 时:
    - 空格需转成 `%s`（或整体加引号）
    - `$` / `"` / `\\` / ``` 需 `\\` 转义
    """
    mapped = (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("`", "\\`")
        .replace("$", "\\$")
    )
    return mapped.replace(" ", "%s")


class AndroidDevice(AbstractInterface):
    """
    Android 设备适配器.

    使用示例::

        from pymidscene.android import AndroidDevice
        device = AndroidDevice("emulator-5554")
        await device.connect()
    """

    interface_type = "android"

    def __init__(
        self,
        device_id: str,
        options: Optional[AndroidDeviceOpt] = None,
    ) -> None:
        if not device_id:
            raise ValueError("device_id is required for AndroidDevice")
        if not _HAS_ADBUTILS:
            raise RuntimeError(
                "adbutils is not installed. Install the android extra: "
                "`pip install pymidscene[android]` or `pip install adbutils`."
            )

        self.device_id = device_id
        self.options: AndroidDeviceOpt = options or AndroidDeviceOpt()
        self._adb_device: Any = None  # adbutils.AdbDevice (lazy)
        self._adb_client: Any = None
        self._destroyed = False
        self._yadb_pushed = False

        # 屏幕信息缓存
        self._cached_screen_size: Optional[dict[str, Any]] = None
        self._cached_orientation: Optional[int] = None
        self._device_pixel_ratio: float = 1.0
        self._device_pixel_ratio_initialized = False
        self._scaling_ratio: float = 1.0

        # app name mapping：用户自定义优先级高于默认
        self._app_name_mapping: dict[str, str] = {
            **DEFAULT_APP_NAME_MAPPING,
            **self.options.app_name_mapping,
        }

        self.description: Optional[str] = None
        self.uri: Optional[str] = None

    # ------------------------------------------------------------------
    # 连接与生命周期
    # ------------------------------------------------------------------

    def set_app_name_mapping(self, mapping: dict[str, str]) -> None:
        """对齐 JS `setAppNameMapping`. 覆盖当前映射."""
        self._app_name_mapping = dict(mapping)

    async def connect(self) -> None:
        """建立 adb 连接. 多次调用幂等. 对齐 JS `connect`."""
        if self._destroyed:
            raise RuntimeError(
                f"AndroidDevice {self.device_id} has been destroyed and "
                "cannot execute ADB commands"
            )
        if self._adb_device is not None:
            return
        await asyncio.to_thread(self._connect_sync)
        # 连接后立即填充 description
        try:
            size_info = await self._get_screen_size_raw(force=True)
            self.description = (
                f"DeviceId: {self.device_id}\n"
                f"ScreenSize:\n"
                f"  override: {size_info.get('override')}\n"
                f"  physical: {size_info.get('physical')}\n"
                f"  orientation: {size_info.get('orientation')}\n"
            )
        except Exception as exc:  # pragma: no cover - best effort
            logger.debug(f"Failed to describe android device: {exc}")

    def _connect_sync(self) -> None:
        """同步建立 adb 连接（在工作线程里调用）."""
        assert adbutils is not None
        adb_host = (
            self.options.remote_adb_host
            or os.environ.get(MIDSCENE_ADB_REMOTE_HOST)
        )
        adb_port = self.options.remote_adb_port or os.environ.get(
            MIDSCENE_ADB_REMOTE_PORT
        )
        adb_path = self.options.android_adb_path or os.environ.get(
            MIDSCENE_ADB_PATH
        )

        if adb_path:
            # adbutils 通过环境变量 ADB_PATH 指定 adb 可执行文件位置
            os.environ.setdefault("ADB_PATH", adb_path)

        if adb_host:
            port = int(adb_port) if adb_port else 5037
            self._adb_client = adbutils.AdbClient(host=adb_host, port=port)
        else:
            self._adb_client = adbutils.adb

        self._adb_device = self._adb_client.device(serial=self.device_id)
        # 触发一次连接验证
        try:
            self._adb_device.prop.name  # 访问属性即会触发通信
        except Exception as exc:
            raise RuntimeError(
                f"Unable to connect to device {self.device_id}: {exc}. "
                "Check `adb devices` or docs at "
                "https://midscenejs.com/integrate-with-android.html#faq"
            ) from exc

    def _require_device(self) -> Any:
        if self._adb_device is None:
            raise RuntimeError(
                f"AndroidDevice {self.device_id} is not connected. "
                "Call await device.connect() first."
            )
        return self._adb_device

    async def destroy(self) -> None:
        """对齐 JS `destroy`. 断开连接, 标记不可用."""
        if self._destroyed:
            return
        self._destroyed = True
        self._adb_device = None
        self._adb_client = None
        self._yadb_pushed = False

    def describe(self) -> str:
        """对齐 JS `describe`."""
        return self.description or f"DeviceId: {self.device_id}"

    # ------------------------------------------------------------------
    # shell helpers
    # ------------------------------------------------------------------

    def _display_arg(self) -> str:
        """对齐 JS `getDisplayArg` - 返回 ` -d <id>` 或 ``""``."""
        if self.options.display_id is not None:
            return f" -d {self.options.display_id}"
        return ""

    async def shell(self, command: str) -> str:
        """
        执行 adb shell 命令, 返回 stdout 字符串.

        对齐 JS 的 `adb.shell`.
        """
        device = self._require_device()
        return await asyncio.to_thread(device.shell, command)

    async def run_adb_shell(self, command: str) -> str:
        """对齐 JS `AndroidAgent.runAdbShell`."""
        if not command or not command.strip():
            raise ValueError("RunAdbShell requires a non-empty command")
        return await self.shell(command)

    # ------------------------------------------------------------------
    # 屏幕尺寸/方向/密度
    # ------------------------------------------------------------------

    async def _get_screen_size_raw(self, force: bool = False) -> dict[str, Any]:
        """
        对齐 JS `getScreenSize`. 返回 ``{'override', 'physical', 'orientation',
        'isCurrentOrientation'}``.
        """
        should_cache = not (self.options.always_refresh_screen_info or force)
        if should_cache and self._cached_screen_size:
            return self._cached_screen_size

        stdout = await self.shell("wm size")
        override_match = re.search(r"Override size: ([^\r\n]+)", stdout)
        physical_match = re.search(r"Physical size: ([^\r\n]+)", stdout)

        override = override_match.group(1).strip() if override_match else ""
        physical = physical_match.group(1).strip() if physical_match else ""
        if not override and not physical:
            raise RuntimeError(f"Failed to get screen size, output: {stdout}")

        orientation = await self._get_display_orientation()
        result = {
            "override": override,
            "physical": physical,
            "orientation": orientation,
            "isCurrentOrientation": False,  # wm size 输出是原生方向
        }
        if not self.options.always_refresh_screen_info:
            self._cached_screen_size = result
        return result

    async def _get_display_orientation(self) -> int:
        """对齐 JS `getDisplayOrientation`. 0=portrait 1=landscape ..."""
        if (
            not self.options.always_refresh_screen_info
            and self._cached_orientation is not None
        ):
            return self._cached_orientation

        orientation = 0
        try:
            stdout = await self.shell(
                f"dumpsys{self._display_arg()} input"
            )
            match = re.search(r"SurfaceOrientation:\s*(\d)", stdout)
            if match:
                orientation = int(match.group(1))
            else:
                raise RuntimeError("no SurfaceOrientation in input")
        except Exception:
            try:
                stdout = await self.shell(
                    f"dumpsys{self._display_arg()} display"
                )
                match = re.search(r"mCurrentOrientation=(\d)", stdout)
                if match:
                    orientation = int(match.group(1))
            except Exception:
                orientation = 0

        if not self.options.always_refresh_screen_info:
            self._cached_orientation = orientation
        return orientation

    async def _get_display_density(self) -> int:
        """对齐 JS `getDisplayDensity`."""
        try:
            stdout = await self.shell("wm density")
            # 输出形如: "Physical density: 420\n Override density: 480"
            override = re.search(r"Override density: (\d+)", stdout)
            if override:
                return int(override.group(1))
            physical = re.search(r"Physical density: (\d+)", stdout)
            if physical:
                return int(physical.group(1))
        except Exception as exc:
            logger.debug(f"Failed to get display density: {exc}")
        return 160  # Android 标准密度

    async def _initialize_device_pixel_ratio(self) -> None:
        if self._device_pixel_ratio_initialized:
            return
        density = await self._get_display_density()
        self._device_pixel_ratio = density / 160
        self._device_pixel_ratio_initialized = True
        logger.debug(
            f"Android dpr initialized: density={density}, dpr={self._device_pixel_ratio}"
        )

    async def get_size(self) -> Size:
        """
        返回逻辑像素尺寸 + dpr. 对齐 JS `size()`.

        - width/height 经过 scaling_ratio 缩放, 作为 AI 坐标空间
        - dpr 供上层 agent 做截图与坐标对齐
        """
        await self._initialize_device_pixel_ratio()
        info = await self._get_screen_size_raw()
        raw = info["override"] or info["physical"]
        match = re.match(r"(\d+)x(\d+)", raw)
        if not match:
            raise RuntimeError(f"Unable to parse screen size: {raw}")

        orientation = int(info.get("orientation", 0))
        is_landscape = orientation in (1, 3)
        should_swap = (not info.get("isCurrentOrientation", False)) and is_landscape
        width = int(match.group(2 if should_swap else 1))
        height = int(match.group(1 if should_swap else 2))

        scale = (
            self.options.screenshot_resize_scale
            if self.options.screenshot_resize_scale is not None
            else 1 / self._device_pixel_ratio
        )
        self._scaling_ratio = scale

        return {
            "width": round(width * scale),
            "height": round(height * scale),
            "dpr": self._device_pixel_ratio,
        }

    def _adjust_coordinates(self, x: float, y: float) -> tuple[int, int]:
        """把 AI 坐标空间的 (x,y) 转成物理像素, 对齐 JS `adjustCoordinates`."""
        scale = self._scaling_ratio or 1.0
        return round(x / scale), round(y / scale)

    # ------------------------------------------------------------------
    # 截图
    # ------------------------------------------------------------------

    async def screenshot(self, full_page: bool = False) -> str:
        """
        返回 PNG base64 字符串. 对齐 JS `screenshotBase64`.

        - 优先 adbutils 的 `screenshot()` (返回 PIL.Image)
        - 校验大小; 若过小 fallback 到 `screencap` + `adb pull`
        """
        _ = full_page  # Android 无「完整页」概念, 只能截当前屏
        device = self._require_device()

        min_bytes = self.options.min_screenshot_buffer_size or 0

        png_bytes: Optional[bytes] = None
        try:
            img = await asyncio.to_thread(
                self._screenshot_via_adbutils, device
            )
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            data = buf.getvalue()
            if min_bytes > 0 and len(data) < min_bytes:
                raise RuntimeError(
                    f"Screenshot buffer too small: {len(data)} bytes"
                )
            png_bytes = data
        except Exception as exc:
            logger.debug(
                f"adbutils screenshot failed, fallback to screencap: {exc}"
            )
            png_bytes = await self._screenshot_via_screencap()

        if not png_bytes:
            raise RuntimeError("Failed to capture screenshot: all methods failed")
        if min_bytes > 0 and len(png_bytes) < min_bytes:
            raise RuntimeError(
                f"Screenshot buffer too small: {len(png_bytes)} bytes "
                f"(minimum: {min_bytes})"
            )
        return base64.b64encode(png_bytes).decode("ascii")

    def _screenshot_via_adbutils(self, device: Any) -> Any:
        """adbutils 的 screenshot. 支持 display_id."""
        display_id = self.options.display_id
        if display_id is not None:
            try:
                return device.screenshot(display_id=display_id)
            except TypeError:
                # 旧版本 adbutils 不支持 display_id 参数
                pass
        return device.screenshot()

    async def _screenshot_via_screencap(self) -> bytes:
        """shell screencap + adb pull 的 fallback 实现."""
        device = self._require_device()
        remote_path = f"/data/local/tmp/midscene_screenshot_{int(time.time()*1000)}.png"
        display_arg = (
            f" -d {self.options.display_id}"
            if self.options.display_id is not None
            else ""
        )
        try:
            await self.shell(f"screencap -p{display_arg} {remote_path}")
            data = await asyncio.to_thread(self._sync_pull_bytes, device, remote_path)
            return data
        finally:
            try:
                await self.shell(f"rm {remote_path}")
            except Exception as exc:  # pragma: no cover
                logger.debug(f"Failed to delete remote screenshot: {exc}")

    @staticmethod
    def _sync_pull_bytes(device: Any, remote_path: str) -> bytes:
        """把远程文件拉到内存. adbutils 的 sync API."""
        sync = device.sync
        buf = io.BytesIO()
        for chunk in sync.iter_content(remote_path):
            buf.write(chunk)
        return buf.getvalue()

    # ------------------------------------------------------------------
    # 基础指针操作 — AbstractInterface 合约
    # ------------------------------------------------------------------

    async def click(self, x: float, y: float) -> None:
        """对齐 JS `mouseClick`. 通过 swipe 实现 0-距离点击, 更可靠."""
        await self._initialize_device_pixel_ratio()
        await self.get_size()  # 确保 scaling_ratio 已计算
        ax, ay = self._adjust_coordinates(x, y)
        await self.shell(
            f"input{self._display_arg()} swipe {ax} {ay} {ax} {ay} 150"
        )

    async def double_click(self, x: float, y: float) -> None:
        """对齐 JS `mouseDoubleClick`."""
        await self._initialize_device_pixel_ratio()
        await self.get_size()
        ax, ay = self._adjust_coordinates(x, y)
        tap_cmd = f"input{self._display_arg()} tap {ax} {ay}"
        await self.shell(tap_cmd)
        await asyncio.sleep(0.05)
        await self.shell(tap_cmd)

    async def long_press(self, x: float, y: float, duration: int = 2000) -> None:
        """对齐 JS `longPress`. duration 单位毫秒."""
        await self._initialize_device_pixel_ratio()
        await self.get_size()
        ax, ay = self._adjust_coordinates(x, y)
        await self.shell(
            f"input{self._display_arg()} swipe {ax} {ay} {ax} {ay} {int(duration)}"
        )

    async def hover(self, x: float, y: float) -> None:
        """触摸屏无 hover 概念, 兼容 AbstractInterface 返回空."""
        return None

    async def mouse_drag(
        self,
        from_xy: tuple[float, float],
        to_xy: tuple[float, float],
        duration: Optional[int] = None,
    ) -> None:
        """对齐 JS `mouseDrag`. duration ms."""
        await self._initialize_device_pixel_ratio()
        await self.get_size()
        fx, fy = self._adjust_coordinates(*from_xy)
        tx, ty = self._adjust_coordinates(*to_xy)
        dur = duration if duration is not None else DEFAULT_NORMAL_SCROLL_DURATION_MS
        await self.shell(
            f"input{self._display_arg()} swipe {fx} {fy} {tx} {ty} {int(dur)}"
        )

    async def drag_and_drop(
        self,
        from_xy: tuple[float, float],
        to_xy: tuple[float, float],
    ) -> None:
        """Agent 侧 ai_drag_drop 使用的钩子. 默认 drag 时长 600ms, 更接近 UX 期望."""
        await self.mouse_drag(from_xy, to_xy, duration=600)

    # ------------------------------------------------------------------
    # 滚动
    # ------------------------------------------------------------------

    async def scroll(
        self,
        direction: str,
        distance: Optional[int] = None,
    ) -> None:
        """
        AbstractInterface 契约: ``scroll(direction, distance)``.

        语义与 JS `scroll(deltaX, deltaY)` 对齐:
        - direction='down' → 屏幕内容上移 (swipe 自底向顶)
        - direction='up' → 屏幕内容下移
        - direction='left'/'right' 同理

        distance 为屏幕像素 (AI 坐标空间). 默认使用屏幕宽/高.
        """
        direction = (direction or "down").lower()
        if direction not in ("up", "down", "left", "right"):
            raise ValueError(f"Unknown scroll direction: {direction}")

        size = await self.get_size()
        width = int(size["width"])
        height = int(size["height"])
        if direction in ("up", "down"):
            d = int(distance) if distance else height
            delta = (0, -d if direction == "up" else d)
        else:
            d = int(distance) if distance else width
            delta = (-d if direction == "left" else d, 0)
        await self._scroll_raw(delta[0], delta[1])

    async def _scroll_raw(
        self,
        delta_x: int,
        delta_y: int,
        duration: Optional[int] = None,
    ) -> None:
        """对齐 JS `scroll(deltaX, deltaY, duration)`. 计算起止点并 swipe."""
        if delta_x == 0 and delta_y == 0:
            raise ValueError("Scroll distance cannot be zero in both directions")
        size = await self.get_size()
        width = int(size["width"])
        height = int(size["height"])
        n = 4
        start_x = round((n - 1) * (width / n)) if delta_x < 0 else round(width / n)
        start_y = (
            round((n - 1) * (height / n)) if delta_y < 0 else round(height / n)
        )
        max_neg_x = start_x
        max_pos_x = round((n - 1) * (width / n))
        max_neg_y = start_y
        max_pos_y = round((n - 1) * (height / n))
        delta_x = max(-max_neg_x, min(delta_x, max_pos_x))
        delta_y = max(-max_neg_y, min(delta_y, max_pos_y))
        end_x = round(start_x - delta_x)
        end_y = round(start_y - delta_y)
        asx, asy = self._adjust_coordinates(start_x, start_y)
        aex, aey = self._adjust_coordinates(end_x, end_y)
        dur = duration if duration is not None else DEFAULT_NORMAL_SCROLL_DURATION_MS
        await self.shell(
            f"input{self._display_arg()} swipe {asx} {asy} {aex} {aey} {int(dur)}"
        )

    async def scroll_until_top(
        self, start_point: Optional[tuple[float, float]] = None
    ) -> None:
        """对齐 JS `scrollUntilTop`."""
        size = await self.get_size()
        if start_point:
            start = (round(start_point[0]), round(start_point[1]))
            end = (start[0], round(size["height"]))
            for _ in range(DEFAULT_SCROLL_UNTIL_TIMES):
                await self.mouse_drag(
                    start, end, duration=DEFAULT_FAST_SCROLL_DURATION_MS
                )
        else:
            for _ in range(DEFAULT_SCROLL_UNTIL_TIMES):
                await self._scroll_raw(
                    0, -9_999_999, duration=DEFAULT_FAST_SCROLL_DURATION_MS
                )
        await asyncio.sleep(1)

    async def scroll_until_bottom(
        self, start_point: Optional[tuple[float, float]] = None
    ) -> None:
        """对齐 JS `scrollUntilBottom`."""
        if start_point:
            start = (round(start_point[0]), round(start_point[1]))
            end = (start[0], 0)
            for _ in range(DEFAULT_SCROLL_UNTIL_TIMES):
                await self.mouse_drag(
                    start, end, duration=DEFAULT_FAST_SCROLL_DURATION_MS
                )
        else:
            for _ in range(DEFAULT_SCROLL_UNTIL_TIMES):
                await self._scroll_raw(
                    0, 9_999_999, duration=DEFAULT_FAST_SCROLL_DURATION_MS
                )
        await asyncio.sleep(1)

    async def scroll_until_left(
        self, start_point: Optional[tuple[float, float]] = None
    ) -> None:
        """对齐 JS `scrollUntilLeft`."""
        size = await self.get_size()
        if start_point:
            start = (round(start_point[0]), round(start_point[1]))
            end = (round(size["width"]), start[1])
            for _ in range(DEFAULT_SCROLL_UNTIL_TIMES):
                await self.mouse_drag(
                    start, end, duration=DEFAULT_FAST_SCROLL_DURATION_MS
                )
        else:
            for _ in range(DEFAULT_SCROLL_UNTIL_TIMES):
                await self._scroll_raw(
                    -9_999_999, 0, duration=DEFAULT_FAST_SCROLL_DURATION_MS
                )
        await asyncio.sleep(1)

    async def scroll_until_right(
        self, start_point: Optional[tuple[float, float]] = None
    ) -> None:
        """对齐 JS `scrollUntilRight`."""
        if start_point:
            start = (round(start_point[0]), round(start_point[1]))
            end = (0, start[1])
            for _ in range(DEFAULT_SCROLL_UNTIL_TIMES):
                await self.mouse_drag(
                    start, end, duration=DEFAULT_FAST_SCROLL_DURATION_MS
                )
        else:
            for _ in range(DEFAULT_SCROLL_UNTIL_TIMES):
                await self._scroll_raw(
                    9_999_999, 0, duration=DEFAULT_FAST_SCROLL_DURATION_MS
                )
        await asyncio.sleep(1)

    async def pull_down(
        self,
        start_point: Optional[tuple[float, float]] = None,
        distance: Optional[int] = None,
        duration: int = 800,
    ) -> None:
        """下拉刷新. 对齐 JS `pullDown`."""
        size = await self.get_size()
        width = int(size["width"])
        height = int(size["height"])
        start = (
            (round(start_point[0]), round(start_point[1]))
            if start_point
            else (round(width / 2), round(height * 0.15))
        )
        pull_distance = round(distance or height * 0.5)
        end = (start[0], start[1] + pull_distance)
        await self.mouse_drag(start, end, duration=duration)
        await asyncio.sleep(0.2)

    async def pull_up(
        self,
        start_point: Optional[tuple[float, float]] = None,
        distance: Optional[int] = None,
        duration: int = 600,
    ) -> None:
        """上拉加载. 对齐 JS `pullUp`."""
        size = await self.get_size()
        width = int(size["width"])
        height = int(size["height"])
        start = (
            (round(start_point[0]), round(start_point[1]))
            if start_point
            else (round(width / 2), round(height * 0.85))
        )
        pull_distance = round(distance or height * 0.4)
        end = (start[0], start[1] - pull_distance)
        await self.mouse_drag(start, end, duration=duration)
        await asyncio.sleep(0.1)

    # ------------------------------------------------------------------
    # 键盘 & 输入
    # ------------------------------------------------------------------

    async def key_press(self, key: str) -> None:
        """对齐 JS `keyboardPress`."""
        if not key:
            return
        normalized = _KEY_NAME_NORMALIZE.get(key.lower(), key)
        key_code = _KEY_CODE_MAP.get(normalized)
        if key_code is not None:
            await self.shell(f"input{self._display_arg()} keyevent {key_code}")
            return
        if len(key) == 1:
            ch = key.upper()
            ascii_code = ord(ch)
            if 65 <= ascii_code <= 90:  # A-Z
                await self.shell(
                    f"input{self._display_arg()} keyevent {ascii_code - 36}"
                )
                return
            if 48 <= ascii_code <= 57:  # 0-9
                await self.shell(
                    f"input{self._display_arg()} keyevent {ascii_code - 41}"
                )
                return
        logger.warning(f"Unknown key name for Android: {key}")

    async def input_text(
        self,
        text: str,
        x: Optional[float] = None,
        y: Optional[float] = None,
        clear_first: bool = False,
    ) -> None:
        """
        AbstractInterface 合约的输入方法.

        流程:
        1. 如果 x/y 有值 -> 先点击 (让目标输入框获取焦点)
        2. 如果 clear_first=True -> 清空现有内容
        3. 用 `keyboard_type` 输入新文本

        空 text + clear_first=True 表示"只清空".
        """
        if x is not None and y is not None:
            await self.click(x, y)
            await asyncio.sleep(0.1)
        if clear_first:
            await self.clear_input()
        if text:
            await self.keyboard_type(text)

    async def keyboard_type(self, text: str) -> None:
        """
        对齐 JS `keyboardType`. 根据 IME 策略选择输入方式.
        """
        if not text:
            return
        use_yadb = _should_use_yadb(text)
        strategy = (
            self.options.ime_strategy
            or os.environ.get(MIDSCENE_ANDROID_IME_STRATEGY)
            or IME_STRATEGY_ADB_KEYBOARD
        )

        if strategy == IME_STRATEGY_ALWAYS_YADB or (
            strategy == IME_STRATEGY_YADB_FOR_NON_ASCII and use_yadb
        ):
            # yadb 需要推送 Java payload, 目前 Python 版未移植; 记日志并尝试
            # ADBKeyboard 或 `input text` 作为退路.
            logger.warning(
                "yadb IME strategy is not yet ported to Python; "
                "falling back to ADBKeyboard / input text. "
                "Install ADBKeyboard and set it as the default IME for "
                "reliable non-ASCII input."
            )
            ok = await self._type_via_adb_keyboard(text)
            if not ok:
                await self._type_via_input_text(text)
            return

        if strategy == IME_STRATEGY_ADB_KEYBOARD and use_yadb:
            ok = await self._type_via_adb_keyboard(text)
            if ok:
                if self.options.auto_dismiss_keyboard:
                    await self.hide_keyboard()
                return
            logger.warning(
                "ADBKeyboard broadcast failed; falling back to `input text`. "
                "Non-ASCII characters may not work. Install "
                "ADBKeyboard.apk + `adb shell ime set com.android.adbkeyboard/.AdbIME`."
            )

        await self._type_via_input_text(text)
        if self.options.auto_dismiss_keyboard:
            await self.hide_keyboard()

    async def _type_via_input_text(self, text: str) -> None:
        """`input text` via shell, 仅对 ASCII/英文安全."""
        escaped = _shell_escape(text)
        await self.shell(f'input{self._display_arg()} text "{escaped}"')

    async def _type_via_adb_keyboard(self, text: str) -> bool:
        """ADBKeyboard 广播输入. 设备需预装 ADBKeyboard.apk 并设为默认 IME."""
        try:
            # 转义 double-quote / backslash
            msg = text.replace("\\", "\\\\").replace('"', '\\"')
            cmd = (
                f'am broadcast -a ADB_INPUT_TEXT --es msg "{msg}"'
            )
            out = await self.shell(cmd)
            # 正常广播输出包含 "Broadcast completed: result=-1"
            return "Broadcast completed" in out or "result=-1" in out
        except Exception as exc:
            logger.debug(f"ADBKeyboard broadcast failed: {exc}")
            return False

    async def clear_input(self) -> None:
        """
        清空当前焦点输入框. 对齐 JS `clearInput`.

        策略: KEYCODE_MOVE_END 移到末尾, 然后批量 DEL.
        """
        # 光标移到末尾: KEYCODE_MOVE_END (123)
        await self.shell(f"input{self._display_arg()} keyevent 123")
        # 批量删除
        dels = " ".join(["67"] * 100)
        await self.shell(f"input{self._display_arg()} keyevent {dels}")

    async def hide_keyboard(self, timeout_ms: int = 1000) -> bool:
        """对齐 JS `hideKeyboard`. 失败返回 False."""
        device = self._require_device()
        strategy = self.options.keyboard_dismiss_strategy or "esc-first"
        # 检查键盘状态
        is_shown = await asyncio.to_thread(self._is_keyboard_shown, device)
        if not is_shown:
            return False
        key_codes = [111, 4] if strategy == "esc-first" else [4, 111]
        interval = 0.1
        for key_code in key_codes:
            await self.shell(f"input{self._display_arg()} keyevent {key_code}")
            deadline = time.time() + timeout_ms / 1000
            while time.time() < deadline:
                await asyncio.sleep(interval)
                still = await asyncio.to_thread(self._is_keyboard_shown, device)
                if not still:
                    return True
        logger.warning(
            "Failed to hide the software keyboard after trying ESC + BACK"
        )
        return False

    @staticmethod
    def _is_keyboard_shown(device: Any) -> bool:
        """检查软键盘是否可见. adbutils 无直接 API; 使用 dumpsys."""
        try:
            out = device.shell("dumpsys input_method | grep mInputShown")
            match = re.search(r"mInputShown=(true|false)", out)
            if match:
                return match.group(1) == "true"
        except Exception:
            pass
        return False

    # ------------------------------------------------------------------
    # Android 专属: 启动 / 物理按键
    # ------------------------------------------------------------------

    async def launch(self, uri: str) -> "AndroidDevice":
        """
        启动应用或打开 URL. 对齐 JS `launch`.

        识别规则:
        - 含 `://` 的视为 URI  → `am start -a VIEW`
        - 含 `/` 视为 `package/activity` 组合 → `am start -n`
        - 其它视为 package 名或 app 名 (查 app_name_mapping)
        """
        if not uri or not uri.strip():
            raise ValueError("launch requires a non-empty uri")
        self.uri = uri

        if "://" in uri:
            await self.shell(
                f'am start -a android.intent.action.VIEW -d "{uri}"'
            )
        elif "/" in uri:
            pkg, activity = uri.split("/", 1)
            await self.shell(f"am start -n {pkg}/{activity}")
        else:
            resolved = resolve_package_name(uri, self._app_name_mapping) or uri
            # 使用 monkey 启动 launcher intent (比 am start 更通用, 无需知道 activity)
            await self.shell(
                f"monkey -p {resolved} -c android.intent.category.LAUNCHER 1"
            )
        return self

    async def back(self) -> None:
        """对齐 JS `back`. KEYCODE_BACK=4."""
        await self.shell(f"input{self._display_arg()} keyevent 4")

    async def home(self) -> None:
        """对齐 JS `home`. KEYCODE_HOME=3."""
        await self.shell(f"input{self._display_arg()} keyevent 3")

    async def recent_apps(self) -> None:
        """对齐 JS `recentApps`. KEYCODE_APP_SWITCH=187."""
        await self.shell(f"input{self._display_arg()} keyevent 187")

    # ------------------------------------------------------------------
    # Web-only 接口的 Android 行为
    # ------------------------------------------------------------------

    async def wait_for_navigation(self, timeout: Optional[int] = None) -> None:
        """Android 无直接对应概念, 短暂等待以让 UI 稳定."""
        await asyncio.sleep(0.3)

    async def wait_for_network_idle(self, timeout: Optional[int] = None) -> None:
        """Android 暂无通用网络空闲检测, 保持兼容."""
        await asyncio.sleep(0.3)

    async def evaluate_javascript(self, script: str) -> Any:
        """
        核心 Agent 在若干路径上会调 `evaluate_javascript`. Android 无 JS 引擎,
        但能识别几个常见模式并转译为原生操作:

        - ``window.scrollTo(0, 0)`` → ``scroll_until_top``
        - ``window.scrollTo(0, document.body.scrollHeight)`` → ``scroll_until_bottom``
        - ``window.history.back()`` → ``back``

        其它脚本记日志并忽略 (对 Android 无意义).
        """
        if not script:
            return None
        s = script.strip()
        if "window.scrollTo(0, 0)" in s:
            await self.scroll_until_top()
            return None
        if "document.body.scrollHeight" in s:
            await self.scroll_until_bottom()
            return None
        if "window.history.back" in s:
            await self.back()
            return None
        logger.debug(f"evaluate_javascript ignored on Android: {s[:80]}")
        return None

    # ------------------------------------------------------------------
    # UI 上下文 (供上层 Agent 使用)
    # ------------------------------------------------------------------

    async def get_ui_context(self) -> UIContext:
        """获取当前 UI 上下文. 与 WebPage 实现保持形状一致."""
        screenshot_data = await self.screenshot()
        size = await self.get_size()

        class AndroidUIContext(UIContext):
            def __init__(self, screenshot: ScreenshotItem, size: Size):
                self.screenshot = screenshot
                self.size = size
                self._is_frozen = False

        return AndroidUIContext(
            screenshot=ScreenshotItem(screenshot_data),
            size=size,
        )


__all__ = [
    "AndroidDevice",
    "AndroidDeviceOpt",
    "DEFAULT_MIN_SCREENSHOT_BYTES",
]
