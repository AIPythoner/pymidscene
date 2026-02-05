"""
PlaywrightAgent - 对应 JS 版本的 PlaywrightAgent

简化 API，直接传入 Playwright page 对象即可使用。
与 JS 版本对齐，默认启用日志记录，自动生成 HTML 报告。

示例:
    from playwright.async_api import async_playwright
    from pymidscene import PlaywrightAgent

    # 方式1：通过环境变量配置（推荐）
    os.environ["MIDSCENE_MODEL_NAME"] = "qwen-vl-max"
    os.environ["MIDSCENE_MODEL_API_KEY"] = "your-key"
    os.environ["MIDSCENE_MODEL_BASE_URL"] = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    os.environ["MIDSCENE_MODEL_FAMILY"] = "qwen2.5-vl"

    agent = PlaywrightAgent(page)
    await agent.ai_click("登录按钮")

    # 结束时生成报告
    agent.finish()

    # 方式2：使用上下文管理器（自动生成报告）
    async with PlaywrightAgent(page) as agent:
        await agent.ai_click("登录按钮")
    # 退出时自动调用 finish()
"""

from typing import Optional, Dict, Any, Union
from playwright.async_api import Page as AsyncPlaywrightPage

try:
    from playwright.sync_api import Page as SyncPlaywrightPage
except ImportError:
    SyncPlaywrightPage = None

from .page import WebPage
from ...core.agent.agent import Agent
from ...shared.logger import logger


class PlaywrightAgent:
    """
    Playwright Agent - 简化的 API 入口

    直接传入 Playwright page 对象，无需手动创建 WebPage 适配器。
    对应 JS 版本的 `new PlaywrightAgent(page, opts)`。

    与 JS 版本对齐：
    - 默认启用日志记录
    - 自动在当前目录创建 midscene_run 目录
    - 调用 finish() 或使用上下文管理器自动生成 HTML 报告

    Args:
        page: Playwright Page 实例（支持同步和异步）
        model_config: 模型配置字典，键为环境变量名称
            - MIDSCENE_MODEL_NAME: 模型名称（如 "qwen-vl-max"）
            - MIDSCENE_MODEL_API_KEY: API 密钥
            - MIDSCENE_MODEL_BASE_URL: API 基础 URL
            - MIDSCENE_MODEL_FAMILY: 模型家族（qwen2.5-vl, doubao-vision 等）
        cache_id: 缓存 ID，用于标识缓存文件
        cache_strategy: 缓存策略
            - "read-write": 读写缓存（默认）
            - "read-only": 只读缓存
            - "write-only": 只写缓存
        enable_recording: 是否启用执行记录（默认启用）
        report_dir: 报告保存目录（默认为当前目录）

    示例:
        # 基础用法
        agent = PlaywrightAgent(page)
        await agent.ai_click("登录按钮")
        agent.finish()  # 生成报告

        # 使用上下文管理器（推荐）
        async with PlaywrightAgent(page) as agent:
            await agent.ai_click("登录按钮")
        # 自动生成报告
    """

    def __init__(
        self,
        page: Union[AsyncPlaywrightPage, "SyncPlaywrightPage"],
        model_config: Optional[Dict[str, Any]] = None,
        cache_id: Optional[str] = None,
        cache_strategy: str = "read-write",
        enable_recording: bool = True,  # 默认启用，与 JS 版本对齐
        report_dir: Optional[str] = None,
        wait_for_navigation_timeout: Optional[int] = None,
        wait_for_network_idle_timeout: Optional[int] = None,
    ):
        """初始化 PlaywrightAgent"""
        # 创建 WebPage 适配器
        self._web_page = WebPage(
            page,
            wait_for_navigation_timeout=wait_for_navigation_timeout,
            wait_for_network_idle_timeout=wait_for_network_idle_timeout,
        )

        # 创建内部 Agent
        self._agent = Agent(
            interface=self._web_page,
            model_config=model_config,
            cache_id=cache_id,
            cache_strategy=cache_strategy,
            enable_recording=enable_recording,
            driver_type="playwright",
            report_dir=report_dir,
        )

        # 保存原始 page 引用
        self.page = page

        logger.info(
            f"PlaywrightAgent initialized: "
            f"cache_id={cache_id}, recording={enable_recording}"
        )

    # ==================== 核心 AI 方法 ====================

    async def ai_locate(self, description: str) -> Optional[Dict[str, Any]]:
        """
        AI 元素定位

        Args:
            description: 元素的自然语言描述

        Returns:
            定位结果，包含 center、rect 等信息
        """
        return await self._agent.ai_locate(description)

    async def ai_click(self, description: str) -> bool:
        """
        AI 点击操作

        Args:
            description: 要点击元素的自然语言描述

        Returns:
            是否成功点击
        """
        return await self._agent.ai_click(description)

    async def ai_input(self, description: str, text: str) -> bool:
        """
        AI 输入操作

        Args:
            description: 输入框的自然语言描述
            text: 要输入的文本

        Returns:
            是否成功输入
        """
        return await self._agent.ai_input(description, text)

    async def ai_query(
        self,
        data_schema: Union[str, Dict[str, str]],
        data_description: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        AI 数据提取

        Args:
            data_schema: 数据结构定义
            data_description: 数据描述

        Returns:
            提取的结构化数据
        """
        return await self._agent.ai_query(data_schema, data_description)

    async def ai_assert(self, assertion: str, error_message: Optional[str] = None):
        """
        AI 断言

        Args:
            assertion: 断言条件描述
            error_message: 断言失败时的错误消息

        Raises:
            AssertionError: 断言失败时抛出
        """
        return await self._agent.ai_assert(assertion, error_message)

    async def ai_action(self, action: str) -> bool:
        """
        执行 AI 动作（别名方法，兼容 JS 版本的 aiAction）

        Args:
            action: 动作的自然语言描述

        Returns:
            是否成功执行
        """
        return await self._agent.ai_click(action)

    # ==================== 日志/报告方法 ====================

    def finish(self) -> Optional[str]:
        """
        结束会话并生成 HTML 报告

        与 JS 版本对齐，在任务完成后调用此方法生成可视化报告。
        报告将保存到 midscene_run/report/ 目录。

        Returns:
            报告文件路径（如果启用了记录）
        """
        return self._agent.finish()

    def save_report(self) -> Optional[str]:
        """
        手动保存报告（不结束会话）

        Returns:
            报告文件路径
        """
        return self._agent.save_report()

    def get_report_dir(self) -> Optional[str]:
        """
        获取报告目录路径

        Returns:
            报告目录的绝对路径
        """
        return self._agent.get_report_dir()

    # ==================== 辅助方法 ====================

    def get_cache_stats(self) -> Optional[Dict[str, Any]]:
        """获取缓存统计信息"""
        return self._agent.get_cache_stats()

    @property
    def recorder(self):
        """获取执行记录器"""
        return self._agent.recorder

    @property
    def session_recorder(self):
        """获取会话记录器"""
        return self._agent.session_recorder

    @property
    def interface(self):
        """获取底层 WebPage 接口"""
        return self._web_page

    @property
    def agent(self):
        """获取底层 Agent 实例"""
        return self._agent

    # ==================== 上下文管理器 ====================

    async def __aenter__(self):
        """异步上下文管理器入口"""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器退出 - 自动保存报告"""
        if exc_type and self._agent.session_recorder:
            # 如果有异常，标记当前步骤失败
            if self._agent.session_recorder.current_step:
                self._agent.session_recorder.fail_step(str(exc_val))

        self.finish()
        return False


__all__ = ["PlaywrightAgent"]
