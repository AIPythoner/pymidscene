"""
IOSAgent - 对应 packages/ios/src/agent.ts

基于组合模式的 iOS Agent 入口. 风格与 ``PlaywrightAgent`` / ``AndroidAgent`` 一致.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ..core.agent.agent import Agent
from ..shared.logger import logger
from ..shared.types import LocateResultElement
from .app_name_mapping import DEFAULT_APP_NAME_MAPPING
from .device import IOSDevice


class IOSAgent:
    """
    iOS Agent 入口.

    用法::

        from pymidscene.ios import agent_from_webdriver_agent
        agent = await agent_from_webdriver_agent()  # 需要 WDA 已启动
        await agent.launch("微信")
        await agent.ai_tap("扫一扫")
    """

    def __init__(
        self,
        device: IOSDevice,
        model_config: Optional[Dict[str, Any]] = None,
        cache_id: Optional[str] = None,
        cache_strategy: str = "read-write",
        enable_recording: bool = True,
        report_dir: Optional[str] = None,
        app_name_mapping: Optional[Dict[str, str]] = None,
    ) -> None:
        self._device = device
        merged = {**DEFAULT_APP_NAME_MAPPING, **(app_name_mapping or {})}
        device.set_app_name_mapping(merged)

        self._agent = Agent(
            interface=device,
            model_config=model_config,
            cache_id=cache_id,
            cache_strategy=cache_strategy,
            enable_recording=enable_recording,
            driver_type="ios",
            report_dir=report_dir,
        )
        logger.info(
            f"IOSAgent initialized: device={device.device_id}, "
            f"cache_id={cache_id}, recording={enable_recording}"
        )

    # ==================== AI 方法 (透传) ====================

    async def ai_locate(self, description: str) -> Optional[LocateResultElement]:
        return await self._agent.ai_locate(description)

    async def ai_click(self, description: str) -> bool:
        return await self._agent.ai_click(description)

    async def ai_tap(self, description: str) -> bool:
        return await self._agent.ai_click(description)

    async def ai_input(self, description: str, text: str) -> bool:
        return await self._agent.ai_input(description, text)

    async def ai_query(
        self, data_schema: str | Dict[str, str], use_cache: bool = True
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

    # ==================== iOS 专属 ====================

    async def launch(self, uri: str) -> None:
        await self._device.launch(uri)

    async def activate_app(self, bundle_id: str) -> None:
        await self._device.activate_app(bundle_id)

    async def terminate_app(self, bundle_id: str) -> None:
        await self._device.terminate_app(bundle_id)

    async def home(self) -> None:
        await self._device.home()

    async def app_switcher(self) -> None:
        await self._device.app_switcher()

    async def key_press(self, key: str) -> None:
        await self._device.key_press(key)

    async def long_press(
        self, x: float, y: float, duration_ms: int = 1000
    ) -> None:
        await self._device.long_press(x, y, duration_ms)

    async def drag_and_drop(
        self,
        from_xy: tuple[float, float],
        to_xy: tuple[float, float],
    ) -> None:
        await self._device.drag_and_drop(from_xy, to_xy)

    async def run_wda_request(
        self, method: str, endpoint: str, data: Optional[Dict[str, Any]] = None
    ) -> Any:
        """对齐 JS `runWdaRequest`. iOS 版的"万能调试通道"."""
        return await self._device.run_wda_request(method, endpoint, data)

    # ==================== 日志 / 报告 ====================

    def finish(self) -> Optional[str]:
        return self._agent.finish()

    def save_report(self) -> Optional[str]:
        return self._agent.save_report()

    def get_report_dir(self) -> Optional[str]:
        return self._agent.get_report_dir()

    def get_cache_stats(self) -> Optional[Dict[str, Any]]:
        return self._agent.get_cache_stats()

    # ==================== 属性 ====================

    @property
    def device(self) -> IOSDevice:
        return self._device

    @property
    def interface(self) -> IOSDevice:
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

    # ==================== 上下文 ====================

    async def __aenter__(self) -> "IOSAgent":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        if exc_type and self._agent.session_recorder:
            if self._agent.session_recorder.current_step:
                self._agent.session_recorder.fail_step(str(exc_val))
        self.finish()
        # 关闭 WDA 会话
        try:
            await self._device.destroy()
        except Exception:
            pass
        return False


__all__ = ["IOSAgent"]
