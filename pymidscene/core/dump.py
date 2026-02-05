"""
执行记录系统 (Dump) - 对应 packages/core/src/dump/

这个模块提供执行过程的记录和序列化功能，用于：
- 记录每步执行的截图、AI 调用信息、耗时
- 生成 JSON 格式的执行报告
- 生成 HTML 可视化报告
- 与 JS 版本的 Visualizer 保持兼容
"""

import json
import time
import uuid
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import asdict

from .types import (
    ExecutionDump,
    GroupedActionDump,
    ExecutionTask,
    ExecutionRecorderItem,
    ServiceDump,
    ScreenshotItem,
    AIUsageInfo,
)
from .run_manager import MidsceneRunManager, get_default_run_manager
from .element_marker import ElementMarker, get_default_marker, ActionMarker
from .report_generator import (
    HTMLReportGenerator,
    ReportSession,
    ReportStep,
    get_default_report_generator,
)
from .js_react_report_generator import (
    JSReactReportGenerator,
    get_js_react_report_generator,
)
from ..shared.logger import logger
from ..shared.types import LocateResultElement


class ExecutionRecorder:
    """执行记录器 - 记录单次执行的详细信息"""

    def __init__(self, name: str, description: Optional[str] = None):
        """
        初始化执行记录器

        Args:
            name: 执行名称
            description: 执行描述
        """
        self.name = name
        self.description = description
        self.log_time = time.time()
        self.tasks: List[ExecutionTask] = []
        self.current_task: Optional[ExecutionTask] = None

    def start_task(
        self,
        task_type: str,
        param: Any = None,
        thought: Optional[str] = None
    ) -> ExecutionTask:
        """
        开始记录新任务

        Args:
            task_type: 任务类型 ('locate', 'click', 'input', 'query', 'assert')
            param: 任务参数
            thought: AI 思考内容

        Returns:
            创建的任务对象
        """
        from .types import UIContext
        from typing import cast
        from ..shared.types import ExecutionTaskType, TaskStatus

        task = ExecutionTask(
            type=cast(ExecutionTaskType, task_type),
            param=param,
            thought=thought,
            status=cast(TaskStatus, "pending"),
            recorder=[],
        )

        self.tasks.append(task)
        self.current_task = task

        logger.debug(f"开始记录任务: {task_type}, 参数: {param}")
        return task

    def record_screenshot(self, screenshot: ScreenshotItem, timing: str = "before"):
        """
        记录截图

        Args:
            screenshot: 截图对象
            timing: 时机 ('before', 'after')
        """
        if not self.current_task:
            logger.warning("没有当前任务，无法记录截图")
            return

        record_item = ExecutionRecorderItem(
            type="screenshot",
            ts=time.time(),
            screenshot=screenshot,
            timing=timing
        )

        self.current_task.recorder.append(record_item)
        logger.debug(f"记录截图: {timing}")

    def record_ai_usage(self, usage: AIUsageInfo):
        """
        记录 AI 使用信息

        Args:
            usage: AI 使用信息（tokens, 耗时等）- 可以是 AIUsageInfo 对象或字典
        """
        if not self.current_task:
            logger.warning("没有当前任务，无法记录 AI 使用信息")
            return

        self.current_task.usage = usage
        # 兼容字典和对象两种格式
        if isinstance(usage, dict):
            tokens = usage.get('total_tokens', 'N/A')
        else:
            tokens = usage.total_tokens if usage else 'N/A'
        logger.debug(f"记录 AI 使用: {tokens} tokens")

    def finish_task(
        self,
        status: str = "finished",
        output: Any = None,
        error: Optional[Exception] = None
    ):
        """
        完成当前任务

        Args:
            status: 任务状态 ('finished', 'failed')
            output: 任务输出
            error: 错误信息（如果失败）
        """
        if not self.current_task:
            logger.warning("没有当前任务，无法完成")
            return

        from typing import cast
        from ..shared.types import TaskStatus
        self.current_task.status = cast(TaskStatus, status)
        self.current_task.output = output

        if error:
            self.current_task.error = error
            self.current_task.error_message = str(error)

        logger.debug(f"完成任务: {self.current_task.type}, 状态: {status}")
        self.current_task = None

    def to_dump(self) -> ExecutionDump:
        """
        转换为 ExecutionDump 对象

        Returns:
            ExecutionDump 对象
        """
        return ExecutionDump(
            log_time=self.log_time,
            name=self.name,
            description=self.description,
            tasks=self.tasks,
        )

    def to_json(self) -> str:
        """
        导出为 JSON 字符串

        Returns:
            JSON 字符串
        """
        dump = self.to_dump()
        return json.dumps(dump.to_dict(), indent=2, ensure_ascii=False)


class SessionRecorder:
    """
    会话记录器 - 记录完整的自动化会话

    集成了目录管理、元素标记、HTML报告生成等功能。
    与 JS 版本 Midscene 的日志系统对齐。
    """

    def __init__(
        self,
        driver_type: str = "playwright",
        base_dir: Optional[str] = None,
        auto_save: bool = True,
        session_id: Optional[str] = None,
        use_js_react_report: bool = True,  # 默认使用 JS React 报告生成器
    ):
        """
        初始化会话记录器

        Args:
            driver_type: 驱动类型 ('playwright', 'selenium', 'appium')
            base_dir: 基础目录，默认为当前工作目录
            auto_save: 是否自动保存报告
            session_id: 会话ID，默认自动生成
            use_js_react_report: 是否使用 JS React 报告生成器（与 JS 版本视觉一致）
        """
        self.driver_type = driver_type
        self.auto_save = auto_save
        self.session_id = session_id or uuid.uuid4().hex
        self.use_js_react_report = use_js_react_report

        # 初始化组件
        self.run_manager = MidsceneRunManager(base_dir)
        self.element_marker = get_default_marker()
        self.report_generator = get_default_report_generator()
        
        # JS React 报告生成器（当 use_js_react_report=True 时使用）
        self.js_react_generator: Optional[JSReactReportGenerator] = None
        if use_js_react_report:
            self.js_react_generator = get_js_react_report_generator()

        # 会话数据
        self.start_time = datetime.now()
        self.end_time: Optional[datetime] = None
        self.steps: List[ReportStep] = []
        self.current_step: Optional[ReportStep] = None
        self._step_index = 0
        self._step_start_time: float = 0.0

        # 元数据
        self.page_url: Optional[str] = None
        self.page_title: Optional[str] = None
        self.viewport_size: Optional[Dict[str, int]] = None

        logger.info(f"SessionRecorder initialized: {self.session_id}")

    def set_page_info(
        self,
        url: Optional[str] = None,
        title: Optional[str] = None,
        viewport: Optional[Dict[str, int]] = None
    ):
        """设置页面信息"""
        if url:
            self.page_url = url
        if title:
            self.page_title = title
        if viewport:
            self.viewport_size = viewport

    def start_step(
        self,
        action_type: str,
        prompt: str,
    ) -> ReportStep:
        """
        开始记录新步骤

        Args:
            action_type: 操作类型 ('click', 'input', 'scroll', 'assert', 'query', 'locate')
            prompt: 用户指令/描述

        Returns:
            创建的步骤对象
        """
        self._step_index += 1

        step = ReportStep(
            step_id=uuid.uuid4().hex[:8],
            step_index=self._step_index,
            action_type=action_type,
            prompt=prompt,
            timestamp=datetime.now().isoformat(),
            duration_ms=0,
            status="pending",
        )

        self.steps.append(step)
        self.current_step = step
        self._step_start_time = time.time()

        logger.debug(f"开始步骤 #{self._step_index}: {action_type} - {prompt[:50]}...")
        return step

    def record_screenshot_before(self, screenshot_base64: str):
        """记录操作前截图"""
        if self.current_step:
            self.current_step.screenshot_before = screenshot_base64

    def record_screenshot_after(self, screenshot_base64: str):
        """记录操作后截图"""
        if self.current_step:
            self.current_step.screenshot_after = screenshot_base64

    def record_element_location(
        self,
        bbox: Tuple[int, int, int, int],
        center: Tuple[int, int],
        description: Optional[str] = None,
        draw_marker: bool = True
    ):
        """
        记录元素定位结果

        Args:
            bbox: 边界框 (x1, y1, x2, y2)
            center: 中心点 (x, y)
            description: 元素描述
            draw_marker: 是否在截图上绘制标记
        """
        if not self.current_step:
            return

        self.current_step.element_bbox = list(bbox)
        self.current_step.element_center = list(center)
        self.current_step.element_description = description

        # 在截图上绘制标记
        if draw_marker and self.current_step.screenshot_before:
            marked = self.element_marker.draw_element_with_click(
                self.current_step.screenshot_before,
                bbox,
                center,
                label=description
            )
            self.current_step.screenshot_marked = marked

    def record_ai_info(
        self,
        model: Optional[str] = None,
        tokens: Optional[int] = None,
        response: Optional[str] = None,
        reasoning: Optional[str] = None
    ):
        """记录 AI 调用信息"""
        if not self.current_step:
            return

        if model:
            self.current_step.ai_model = model
        if tokens:
            self.current_step.ai_tokens = tokens
        if response:
            self.current_step.ai_response = response
        if reasoning:
            self.current_step.ai_reasoning = reasoning

    def complete_step(
        self,
        status: str = "success",
        error_message: Optional[str] = None
    ):
        """
        完成当前步骤

        Args:
            status: 状态 ('success', 'failed')
            error_message: 错误信息
        """
        if not self.current_step:
            return

        # 计算耗时
        duration = int((time.time() - self._step_start_time) * 1000)
        self.current_step.duration_ms = duration
        self.current_step.status = status

        if error_message:
            self.current_step.error_message = error_message

        logger.debug(
            f"完成步骤 #{self.current_step.step_index}: "
            f"{status}, {duration}ms"
        )

        self.current_step = None

    def fail_step(self, error_message: str):
        """标记当前步骤失败"""
        self.complete_step(status="failed", error_message=error_message)

    def _build_report_session(self) -> ReportSession:
        """构建报告会话对象"""
        success_count = sum(1 for s in self.steps if s.status == "success")
        failed_count = sum(1 for s in self.steps if s.status == "failed")

        overall_status = "success"
        if failed_count > 0:
            overall_status = "failed"
        elif not self.end_time:
            overall_status = "running"

        return ReportSession(
            session_id=self.session_id,
            driver_type=self.driver_type,
            start_time=self.start_time.isoformat(),
            end_time=self.end_time.isoformat() if self.end_time else None,
            status=overall_status,
            total_steps=len(self.steps),
            success_steps=success_count,
            failed_steps=failed_count,
            steps=self.steps,
            page_url=self.page_url,
            page_title=self.page_title,
            viewport_size=self.viewport_size,
        )

    def generate_report(self) -> str:
        """
        生成 HTML 报告

        Returns:
            HTML 内容
        """
        # 优先使用 JS React 报告生成器
        if self.use_js_react_report and self.js_react_generator:
            return self._generate_js_react_report()
        
        session = self._build_report_session()
        return self.report_generator.generate(session)
    
    def _generate_js_react_report(self) -> str:
        """使用 JS React 报告生成器生成报告"""
        if not self.js_react_generator:
            raise RuntimeError("JS React generator not initialized")
        
        # 初始化会话
        self.js_react_generator.start_session(
            group_name=f"PyMidscene Session - {self.session_id}",
            description=f"Driver: {self.driver_type}",
        )
        
        # 将步骤转换为 JS React 格式
        for step in self.steps:
            # 映射操作类型到 JS 版本格式
            task_type = "Insight"
            sub_type = step.action_type.capitalize()
            
            if step.action_type in ["click", "tap", "input", "scroll"]:
                task_type = "Action Space"
                sub_type = "Tap" if step.action_type in ["click", "tap"] else step.action_type.capitalize()
            elif step.action_type in ["locate"]:
                task_type = "Planning"
                sub_type = "Locate"
            elif step.action_type in ["assert", "query"]:
                task_type = "Insight"
                sub_type = step.action_type.capitalize()
            
            # 转换元素信息
            element_rect = None
            element_center = None
            if step.element_bbox and len(step.element_bbox) == 4:
                element_rect = {
                    "left": step.element_bbox[0],
                    "top": step.element_bbox[1],
                    "width": step.element_bbox[2] - step.element_bbox[0],
                    "height": step.element_bbox[3] - step.element_bbox[1],
                }
            if step.element_center:
                element_center = step.element_center
            
            # 添加任务
            self.js_react_generator.add_task(
                task_type=task_type,
                sub_type=sub_type,
                prompt=step.prompt,
                status="finished" if step.status == "success" else "failed" if step.status == "failed" else "pending",
                screenshot_before=step.screenshot_before,
                screenshot_after=step.screenshot_after,
                element_rect=element_rect,
                element_center=element_center,
                element_text=step.element_description,
                duration_ms=step.duration_ms,
                ai_tokens=step.ai_tokens,
                error=step.error_message,
                thought=step.ai_reasoning,
            )
        
        return self.js_react_generator.generate_html()

    def save_report(self, filename: Optional[str] = None) -> str:
        """
        保存 HTML 报告到文件

        Args:
            filename: 文件名（可选）

        Returns:
            保存的文件路径
        """
        # 优先使用 JS React 报告生成器
        if self.use_js_react_report and self.js_react_generator:
            return self._save_js_react_report(filename)
        
        session = self._build_report_session()
        return self.report_generator.save(
            session,
            str(self.run_manager.report_dir),
            filename
        )
    
    def _save_js_react_report(self, filename: Optional[str] = None) -> str:
        """使用 JS React 报告生成器保存报告"""
        # 先生成报告内容（会初始化会话和添加任务）
        self._generate_js_react_report()
        
        if not self.js_react_generator:
            raise RuntimeError("JS React generator not initialized")
        
        # 保存报告
        return self.js_react_generator.save(
            str(self.run_manager.report_dir),
            self.driver_type,
            filename
        )

    def save_dump(self) -> str:
        """
        保存 JSON 转储文件

        Returns:
            保存的文件路径
        """
        session = self._build_report_session()
        dump_path = self.run_manager.get_dump_file_path(self.session_id)

        with open(dump_path, 'w', encoding='utf-8') as f:
            json.dump(session.to_dict(), f, indent=2, ensure_ascii=False)

        logger.info(f"Dump saved to: {dump_path}")
        return str(dump_path)

    def finish(self) -> Optional[str]:
        """
        结束会话并保存报告

        Returns:
            报告文件路径（如果 auto_save=True）
        """
        self.end_time = datetime.now()

        logger.info(
            f"Session finished: {self.session_id}, "
            f"steps={len(self.steps)}, "
            f"duration={(self.end_time - self.start_time).total_seconds():.1f}s"
        )

        if self.auto_save:
            return self.save_report()

        return None

    def __enter__(self):
        """上下文管理器入口"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器退出"""
        if exc_type:
            # 如果有异常，标记当前步骤失败
            if self.current_step:
                self.fail_step(str(exc_val))

        self.finish()
        return False


class GroupedExecutionRecorder:
    """分组执行记录器 - 管理多个执行记录"""

    def __init__(
        self,
        group_name: str,
        group_description: Optional[str] = None,
        sdk_version: str = "1.0.0"
    ):
        """
        初始化分组记录器

        Args:
            group_name: 分组名称
            group_description: 分组描述
            sdk_version: SDK 版本
        """
        self.group_name = group_name
        self.group_description = group_description
        self.sdk_version = sdk_version
        self.executions: List[ExecutionDump] = []
        self.model_briefs: List[str] = []

    def add_execution(self, execution: ExecutionDump):
        """
        添加执行记录

        Args:
            execution: 执行记录对象
        """
        self.executions.append(execution)
        logger.debug(f"添加执行记录: {execution.name}")

    def add_model_brief(self, model_name: str):
        """
        添加模型简介

        Args:
            model_name: 模型名称
        """
        if model_name not in self.model_briefs:
            self.model_briefs.append(model_name)

    def to_dump(self) -> GroupedActionDump:
        """
        转换为 GroupedActionDump 对象

        Returns:
            GroupedActionDump 对象
        """
        return GroupedActionDump(
            sdk_version=self.sdk_version,
            group_name=self.group_name,
            group_description=self.group_description,
            model_briefs=self.model_briefs,
            executions=self.executions,
        )

    def to_json(self) -> str:
        """
        导出为 JSON 字符串

        Returns:
            JSON 字符串
        """
        dump = self.to_dump()
        return json.dumps(dump.to_dict(), indent=2, ensure_ascii=False)

    def save_to_file(self, file_path: str):
        """
        保存到文件

        Args:
            file_path: 文件路径
        """
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(self.to_json())

        logger.info(f"执行记录已保存到: {file_path}")

    @staticmethod
    def load_from_file(file_path: str) -> 'GroupedExecutionRecorder':
        """
        从文件加载

        Args:
            file_path: 文件路径

        Returns:
            GroupedExecutionRecorder 对象
        """
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        dump = GroupedActionDump.from_dict(data)

        recorder = GroupedExecutionRecorder(
            group_name=dump.group_name,
            group_description=dump.group_description,
            sdk_version=dump.sdk_version
        )
        recorder.executions = dump.executions
        recorder.model_briefs = dump.model_briefs

        logger.info(f"执行记录已从文件加载: {file_path}")
        return recorder


class ServiceDumpBuilder:
    """ServiceDump 构建器 - 用于构建 AI 服务调用的记录"""

    def __init__(self, dump_type: str):
        """
        初始化构建器

        Args:
            dump_type: 记录类型 ('locate', 'extract', 'assert')
        """
        self.dump_type = dump_type
        self.log_id = str(uuid.uuid4())
        self.log_time = time.time()
        self.user_query: Dict[str, Any] = {}
        self.matched_element: List[LocateResultElement] = []
        self.data: Any = None
        self.task_info: Dict[str, Any] = {
            "durationMs": 0,
        }
        self.error: Optional[str] = None

    def set_user_query(self, **kwargs):
        """设置用户查询"""
        self.user_query.update(kwargs)
        return self

    def set_matched_element(self, elements: List[LocateResultElement]):
        """设置匹配的元素"""
        self.matched_element = elements
        return self

    def set_data(self, data: Any):
        """设置数据"""
        self.data = data
        return self

    def set_task_info(self, **kwargs):
        """设置任务信息"""
        self.task_info.update(kwargs)
        return self

    def set_error(self, error: str):
        """设置错误信息"""
        self.error = error
        return self

    def build(self) -> ServiceDump:
        """
        构建 ServiceDump 对象

        Returns:
            ServiceDump 对象
        """
        from .types import ServiceTaskInfo

        task_info = ServiceTaskInfo(
            duration_ms=self.task_info.get("durationMs", 0),
            format_response=self.task_info.get("formatResponse"),
            raw_response=self.task_info.get("rawResponse"),
            usage=self.task_info.get("usage"),
            search_area=self.task_info.get("searchArea"),
            reasoning_content=self.task_info.get("reasoningContent"),
        )

        return ServiceDump(
            type=self.dump_type,
            log_id=self.log_id,
            log_time=self.log_time,
            user_query=self.user_query,
            matched_element=self.matched_element,
            matched_rect=None,
            deep_think=None,
            data=self.data,
            assertion_pass=None,
            assertion_thought=None,
            task_info=task_info,
            error=self.error,
            output=None,
        )


def create_execution_recorder(
    name: str,
    description: Optional[str] = None
) -> ExecutionRecorder:
    """
    创建执行记录器的便捷函数

    Args:
        name: 执行名称
        description: 执行描述

    Returns:
        ExecutionRecorder 对象
    """
    return ExecutionRecorder(name, description)


def create_session_recorder(
    driver_type: str = "playwright",
    base_dir: Optional[str] = None,
    auto_save: bool = True,
    use_js_react_report: bool = True,
) -> SessionRecorder:
    """
    创建会话记录器的便捷函数

    Args:
        driver_type: 驱动类型
        base_dir: 基础目录
        auto_save: 是否自动保存
        use_js_react_report: 是否使用 JS React 报告生成器（与 JS 版本视觉一致）

    Returns:
        SessionRecorder 对象
    """
    return SessionRecorder(driver_type, base_dir, auto_save, use_js_react_report=use_js_react_report)


def create_grouped_recorder(
    group_name: str,
    group_description: Optional[str] = None
) -> GroupedExecutionRecorder:
    """
    创建分组记录器的便捷函数

    Args:
        group_name: 分组名称
        group_description: 分组描述

    Returns:
        GroupedExecutionRecorder 对象
    """
    return GroupedExecutionRecorder(group_name, group_description)


__all__ = [
    "ExecutionRecorder",
    "SessionRecorder",
    "GroupedExecutionRecorder",
    "ServiceDumpBuilder",
    "create_execution_recorder",
    "create_session_recorder",
    "create_grouped_recorder",
]
