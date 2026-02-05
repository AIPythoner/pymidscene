"""
核心类型定义 - 对应 packages/core/src/types.ts

这个模块定义了 PyMidscene 核心功能中使用的类型。
"""

from typing import TypedDict, Optional, List, Dict, Any, Callable, Tuple, Protocol, Literal
from dataclasses import dataclass, field
from abc import ABC, abstractmethod

from ..shared.types import (
    Size,
    Rect,
    LocateResultElement,
    AIUsageInfo,
    TaskStatus,
    ExecutionTaskType,
    ExecutionTaskTiming,
)


# ============================================================================
# UI 上下文
# ============================================================================

class ScreenshotItem:
    """截图项（简化版，完整实现在 screenshot.py）"""
    def __init__(self, data: str):
        self.data = data  # Base64 编码的图像数据

    def to_serializable(self) -> str:
        """转换为可序列化格式"""
        return self.data

    @staticmethod
    def is_serialized_data(value: Any) -> bool:
        """检查是否为序列化数据"""
        return isinstance(value, str)

    @staticmethod
    def from_serialized_data(data: str) -> 'ScreenshotItem':
        """从序列化数据恢复"""
        return ScreenshotItem(data)


@dataclass
class UIContext(ABC):
    """UI 上下文抽象基类"""
    screenshot: ScreenshotItem
    size: Size
    _is_frozen: bool = False


# ============================================================================
# Service 相关类型
# ============================================================================

@dataclass
class ServiceTaskInfo:
    """Service 任务信息"""
    duration_ms: float
    format_response: Optional[str] = None
    raw_response: Optional[str] = None
    usage: Optional[AIUsageInfo] = None
    search_area: Optional[Rect] = None
    search_area_raw_response: Optional[str] = None
    search_area_usage: Optional[AIUsageInfo] = None
    reasoning_content: Optional[str] = None


@dataclass
class ServiceDump:
    """Service 执行记录"""
    type: str  # 'locate' | 'extract' | 'assert'
    log_id: str
    log_time: float
    user_query: Dict[str, Any]
    matched_element: List[LocateResultElement]
    matched_rect: Optional[Rect]
    deep_think: Optional[bool]
    data: Any
    assertion_pass: Optional[bool]
    assertion_thought: Optional[str]
    task_info: ServiceTaskInfo
    error: Optional[str]
    output: Optional[Any]


class ServiceError(Exception):
    """Service 错误"""
    def __init__(self, message: str, dump: ServiceDump):
        super().__init__(message)
        self.dump = dump


# ============================================================================
# 执行任务相关类型
# ============================================================================

@dataclass
class ExecutionRecorderItem:
    """执行记录项"""
    type: str  # 'screenshot'
    ts: float  # 时间戳
    screenshot: Optional[ScreenshotItem] = None
    timing: Optional[str] = None


@dataclass
class ExecutionTaskHitBy:
    """任务命中来源"""
    from_: str  # 使用 from_ 避免与 Python 关键字冲突
    context: Dict[str, Any]


@dataclass
class ExecutorContext:
    """执行器上下文"""
    task: 'ExecutionTask'
    element: Optional[LocateResultElement] = None
    ui_context: Optional[UIContext] = None


# 执行器函数类型
ExecutorFunction = Callable[
    [Any, ExecutorContext],
    Optional[Dict[str, Any]]
]


@dataclass
class ExecutionTask:
    """执行任务"""
    type: ExecutionTaskType
    sub_type: Optional[str] = None
    sub_task: bool = False
    param: Optional[Any] = None
    thought: Optional[str] = None
    ui_context: Optional[UIContext] = None

    # 执行状态
    status: TaskStatus = "pending"
    error: Optional[Exception] = None
    error_message: Optional[str] = None
    error_stack: Optional[str] = None

    # 执行结果
    output: Optional[Any] = None
    log: Optional[Any] = None
    recorder: List[ExecutionRecorderItem] = field(default_factory=list)
    hit_by: Optional[ExecutionTaskHitBy] = None

    # 时间和资源统计
    timing: Optional[ExecutionTaskTiming] = None
    usage: Optional[AIUsageInfo] = None
    search_area_usage: Optional[AIUsageInfo] = None
    reasoning_content: Optional[str] = None


# ============================================================================
# 执行记录（Dump）
# ============================================================================

@dataclass
class DumpMeta:
    """Dump 元数据"""
    log_time: float


@dataclass
class ExecutionDump:
    """执行记录"""
    log_time: float
    name: str
    description: Optional[str]
    tasks: List[ExecutionTask]
    ai_act_context: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（用于序列化）"""
        return {
            "logTime": self.log_time,
            "name": self.name,
            "description": self.description,
            "tasks": [self._task_to_dict(task) for task in self.tasks],
            "aiActContext": self.ai_act_context,
        }

    def _task_to_dict(self, task: ExecutionTask) -> Dict[str, Any]:
        """将任务转换为字典"""
        # 简化实现，实际需要处理所有字段
        return {
            "type": task.type,
            "status": task.status,
            "param": task.param,
            # ... 其他字段
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> 'ExecutionDump':
        """从字典创建实例"""
        return ExecutionDump(
            log_time=data["logTime"],
            name=data["name"],
            description=data.get("description"),
            tasks=[],  # 需要实现完整的反序列化
            ai_act_context=data.get("aiActContext"),
        )


@dataclass
class GroupedActionDump:
    """分组执行记录"""
    sdk_version: str
    group_name: str
    group_description: Optional[str]
    model_briefs: List[str]
    executions: List[ExecutionDump]

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（用于序列化）"""
        return {
            "sdkVersion": self.sdk_version,
            "groupName": self.group_name,
            "groupDescription": self.group_description,
            "modelBriefs": self.model_briefs,
            "executions": [exec.to_dict() for exec in self.executions],
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> 'GroupedActionDump':
        """从字典创建实例"""
        return GroupedActionDump(
            sdk_version=data["sdkVersion"],
            group_name=data["groupName"],
            group_description=data.get("groupDescription"),
            model_briefs=data["modelBriefs"],
            executions=[
                ExecutionDump.from_dict(exec) for exec in data["executions"]
            ],
        )


# ============================================================================
# Planning 相关类型
# ============================================================================

@dataclass
class PlanningAction:
    """规划动作"""
    type: str
    param: Any
    thought: Optional[str] = None
    log: Optional[str] = None


@dataclass
class PlanningAIResponse:
    """AI 规划响应"""
    actions: Optional[List[PlanningAction]] = None
    usage: Optional[AIUsageInfo] = None
    raw_response: Optional[str] = None
    yaml_string: Optional[str] = None
    error: Optional[str] = None
    reasoning_content: Optional[str] = None
    should_continue_planning: bool = False


# ============================================================================
# Agent 配置类型
# ============================================================================

ThinkingLevel = Literal["off", "medium", "high"]
DeepThinkOption = Literal["unset"] | bool


@dataclass
class AgentWaitForOpt:
    """Agent 等待选项"""
    check_interval_ms: int = 1000
    timeout_ms: int = 30000


@dataclass
class AgentAssertOpt:
    """Agent 断言选项"""
    keep_raw_response: bool = False


# ============================================================================
# 导出所有类型
# ============================================================================

__all__ = [
    # UI 上下文
    "ScreenshotItem",
    "UIContext",
    # Service 相关
    "ServiceTaskInfo",
    "ServiceDump",
    "ServiceError",
    # 执行任务
    "ExecutionRecorderItem",
    "ExecutionTaskHitBy",
    "ExecutorContext",
    "ExecutorFunction",
    "ExecutionTask",
    # 执行记录
    "DumpMeta",
    "ExecutionDump",
    "GroupedActionDump",
    # Planning
    "PlanningAction",
    "PlanningAIResponse",
    # Agent 配置
    "ThinkingLevel",
    "DeepThinkOption",
    "AgentWaitForOpt",
    "AgentAssertOpt",
]
