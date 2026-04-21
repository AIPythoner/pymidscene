"""
AndroidAgent - 对应 packages/android/src/agent.ts

基于组合的 Agent 适配器, 与 ``PlaywrightAgent`` 风格一致:

- 内部持有一个 ``AndroidDevice`` (实现 ``AbstractInterface``) 和一个底层 ``Agent``.
- 暴露所有 ``ai_*`` 方法, 以及 Android 专属的 ``back / home / recent_apps /
  launch / run_adb_shell / pull_down / pull_up / long_press / drag_and_drop``.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ..core.agent.agent import Agent
from ..shared.logger import logger
from ..shared.types import LocateResultElement
from .app_name_mapping import DEFAULT_APP_NAME_MAPPING
from .device import AndroidDevice


class AndroidAgent:
    """
    Android 平台的 Agent 入口.

    用法::

        from pymidscene.android import AndroidAgent, AndroidDevice
        device = AndroidDevice("emulator-5554")
        await device.connect()
        agent = AndroidAgent(device)
        await agent.launch("小红书")
        await agent.ai_tap("搜索按钮")
        agent.finish()

    或者使用更便捷的 ``agent_from_adb_device``::

        from pymidscene.android import agent_from_adb_device
        agent = await agent_from_adb_device()
    """

    def __init__(
        self,
        device: AndroidDevice,
        model_config: Optional[Dict[str, Any]] = None,
        cache_id: Optional[str] = None,
        cache_strategy: str = "read-write",
        enable_recording: bool = True,
        report_dir: Optional[str] = None,
        app_name_mapping: Optional[Dict[str, str]] = None,
    ) -> None:
        """
        Args:
            device: 已经 connect() 好的 AndroidDevice 实例.
            model_config: 模型配置 dict (同 PlaywrightAgent).
            cache_id: 缓存 id.
            cache_strategy: ``read-only`` / ``read-write`` / ``write-only``.
            enable_recording: 是否启用执行记录与报告 (默认 True).
            report_dir: 报告输出目录 (默认当前目录下 ``midscene_run``).
            app_name_mapping: 追加的 app 名 → 包名映射 (覆盖默认映射中的同名 key).
        """
        self._device = device

        # 合并用户 app 名映射, 用户优先 (对齐 JS)
        merged = {**DEFAULT_APP_NAME_MAPPING, **(app_name_mapping or {})}
        device.set_app_name_mapping(merged)

        self._agent = Agent(
            interface=device,
            model_config=model_config,
            cache_id=cache_id,
            cache_strategy=cache_strategy,
            enable_recording=enable_recording,
            driver_type="android",
            report_dir=report_dir,
        )

        logger.info(
            f"AndroidAgent initialized: device={device.device_id}, "
            f"cache_id={cache_id}, recording={enable_recording}"
        )

    # ==================== AI 核心方法 ====================

    async def ai_locate(self, description: str) -> Optional[LocateResultElement]:
        return await self._agent.ai_locate(description)

    async def ai_click(self, description: str) -> bool:
        return await self._agent.ai_click(description)

    # 移动端的"点击"更习惯叫 tap, 保留别名.
    async def ai_tap(self, description: str) -> bool:
        return await self._agent.ai_click(description)

    async def ai_input(self, description: str, text: str) -> bool:
        return await self._agent.ai_input(description, text)

    async def ai_query(
        self,
        data_schema: str | Dict[str, str],
        use_cache: bool = True,
    ) -> Dict[str, Any]:
        return await self._agent.ai_query(data_schema, use_cache)

    async def ai_assert(
        self, assertion: str, error_message: Optional[str] = None
    ) -> bool:
        return await self._agent.ai_assert(assertion, error_message or "")

    async def ai_action(self, action: str) -> bool:
        return await self._agent.ai_act(action)

    async def ai_act(self, action: str) -> bool:
        return await self._agent.ai_act(action)

    async def ai_wait_for(
        self,
        assertion: str,
        timeout: float = 30,
        interval: float = 2,
    ) -> bool:
        return await self._agent.ai_wait_for(assertion, timeout, interval)

    async def ai_scroll(
        self,
        direction: str = "down",
        distance: int = 500,
        scroll_type: str = "singleAction",
        locate_prompt: Optional[str] = None,
    ) -> bool:
        return await self._agent.ai_scroll(
            direction, distance, scroll_type, locate_prompt
        )

    # ==================== Android 专属操作 ====================

    async def launch(self, uri: str) -> None:
        """启动 app / 打开 URL. 对齐 JS `AndroidAgent.launch`."""
        await self._device.launch(uri)

    async def run_adb_shell(self, command: str) -> str:
        """执行 adb shell. 对齐 JS `AndroidAgent.runAdbShell`."""
        return await self._device.run_adb_shell(command)

    async def back(self) -> None:
        """系统返回键."""
        await self._device.back()

    async def home(self) -> None:
        """系统 Home 键."""
        await self._device.home()

    async def recent_apps(self) -> None:
        """系统最近应用键."""
        await self._device.recent_apps()

    async def key_press(self, key: str) -> None:
        """按单个键 (Enter / Backspace / 方向键等)."""
        await self._device.key_press(key)

    async def long_press(
        self, x: float, y: float, duration_ms: int = 2000
    ) -> None:
        """对屏幕坐标做长按."""
        await self._device.long_press(x, y, duration_ms)

    async def pull_down(
        self,
        start_point: Optional[tuple[float, float]] = None,
        distance: Optional[int] = None,
        duration_ms: int = 800,
    ) -> None:
        """下拉刷新."""
        await self._device.pull_down(start_point, distance, duration_ms)

    async def pull_up(
        self,
        start_point: Optional[tuple[float, float]] = None,
        distance: Optional[int] = None,
        duration_ms: int = 600,
    ) -> None:
        """上拉加载."""
        await self._device.pull_up(start_point, distance, duration_ms)

    async def drag_and_drop(
        self,
        from_xy: tuple[float, float],
        to_xy: tuple[float, float],
    ) -> None:
        """拖拽手势."""
        await self._device.drag_and_drop(from_xy, to_xy)

    # ==================== 日志 / 报告 ====================

    def finish(self) -> Optional[str]:
        """结束会话并生成 HTML 报告."""
        return self._agent.finish()

    def save_report(self) -> Optional[str]:
        """手动保存报告."""
        return self._agent.save_report()

    def get_report_dir(self) -> Optional[str]:
        return self._agent.get_report_dir()

    def get_cache_stats(self) -> Optional[Dict[str, Any]]:
        return self._agent.get_cache_stats()

    # ==================== 属性访问 ====================

    @property
    def device(self) -> AndroidDevice:
        return self._device

    @property
    def interface(self) -> AndroidDevice:
        return self._device

    @property
    def agent(self) -> Agent:
        return self._agent

    @property
    def recorder(self):
        return self._agent.recorder

    @property
    def session_recorder(self):
        return self._agent.session_recorder

    # ==================== 上下文管理器 ====================

    async def __aenter__(self) -> "AndroidAgent":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        if exc_type and self._agent.session_recorder:
            if self._agent.session_recorder.current_step:
                self._agent.session_recorder.fail_step(str(exc_val))
        self.finish()
        # 不吞异常
        return False


__all__ = ["AndroidAgent"]
