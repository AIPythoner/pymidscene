"""
共享类型定义 - 对应 packages/shared/src/types/index.ts

这个模块定义了 PyMidscene 中使用的基础类型和数据结构。
"""

from typing import TypedDict, Optional, Tuple, List, Any, Dict, Literal
from dataclasses import dataclass, field
from abc import ABC, abstractmethod
from enum import Enum


# ============================================================================
# 基础几何类型
# ============================================================================

class Point(TypedDict):
    """点坐标"""
    left: float
    top: float


class Size(TypedDict):
    """尺寸大小"""
    width: float  # 图像宽度（逻辑像素）
    height: float  # 图像高度（逻辑像素）
    dpr: Optional[float]  # 已废弃，不要使用


class Rect(TypedDict):
    """矩形区域"""
    left: float
    top: float
    width: float
    height: float
    zoom: Optional[float]


# ============================================================================
# UI 元素类型
# ============================================================================

NodeType = str  # 节点类型，如 'BUTTON', 'INPUT' 等


@dataclass
class BaseElement(ABC):
    """UI 元素基类"""
    id: str
    attributes: Dict[str, str]
    content: str
    rect: Rect
    center: Tuple[float, float]
    is_visible: bool


@dataclass
class ElementTreeNode:
    """UI 元素树节点"""
    node: Optional[BaseElement]
    children: List['ElementTreeNode'] = field(default_factory=list)


@dataclass
class LocateResultElement:
    """元素定位结果"""
    description: str  # 元素描述
    center: Tuple[float, float]  # 中心点坐标 [x, y]
    rect: Rect  # 矩形区域


# ============================================================================
# AI 响应类型
# ============================================================================

@dataclass
class AIUsageInfo:
    """AI 使用信息（Token 统计）"""
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    cached_input: Optional[int] = None
    time_cost: Optional[float] = None  # 毫秒
    model_name: Optional[str] = None
    model_description: Optional[str] = None
    intent: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AIElementCoordinatesResponse:
    """AI 元素坐标响应"""
    bbox: Tuple[float, float, float, float]  # [x, y, width, height]
    errors: Optional[List[str]] = None


@dataclass
class AIDataExtractionResponse:
    """AI 数据提取响应"""
    data: Any
    errors: Optional[List[str]] = None
    thought: Optional[str] = None


@dataclass
class AIAssertionResponse:
    """AI 断言响应"""
    pass_: bool  # 使用 pass_ 避免与 Python 关键字冲突
    thought: str


# ============================================================================
# 任务执行类型
# ============================================================================

TaskStatus = Literal["pending", "running", "finished", "failed", "cancelled"]
ExecutionTaskType = Literal["Planning", "Insight", "Action Space", "Log"]
ServiceAction = Literal["locate", "extract", "assert", "describe"]


@dataclass
class ExecutionTaskTiming:
    """任务执行时间统计"""
    start: float  # 时间戳（毫秒）
    end: Optional[float] = None
    cost: Optional[float] = None  # 耗时（毫秒）


@dataclass
class LocateResult:
    """定位结果"""
    element: Optional[LocateResultElement]
    rect: Optional[Rect] = None


# ============================================================================
# 缓存配置类型
# ============================================================================

CacheStrategy = Literal["read-only", "read-write", "write-only"]


@dataclass
class CacheConfig:
    """缓存配置"""
    strategy: CacheStrategy = "read-write"
    id: str = ""


# Cache 可以是 False（禁用）或 CacheConfig 对象
Cache = bool | CacheConfig


# ============================================================================
# 测试相关类型
# ============================================================================

TestStatus = Literal["passed", "failed", "timedOut", "skipped", "interrupted"]


# ============================================================================
# 接口类型
# ============================================================================

InterfaceType = Literal[
    "puppeteer",
    "playwright",
    "static",
    "chrome-extension-proxy",
    "android",
    "ios"
]


# ============================================================================
# 导出所有类型
# ============================================================================

__all__ = [
    # 基础几何类型
    "Point",
    "Size",
    "Rect",
    # UI 元素类型
    "NodeType",
    "BaseElement",
    "ElementTreeNode",
    "LocateResultElement",
    # AI 响应类型
    "AIUsageInfo",
    "AIElementCoordinatesResponse",
    "AIDataExtractionResponse",
    "AIAssertionResponse",
    # 任务执行类型
    "TaskStatus",
    "ExecutionTaskType",
    "ServiceAction",
    "ExecutionTaskTiming",
    "LocateResult",
    # 缓存配置
    "CacheStrategy",
    "CacheConfig",
    "Cache",
    # 测试相关
    "TestStatus",
    # 接口类型
    "InterfaceType",
]
