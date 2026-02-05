"""
PyMidscene Core 模块

提供核心功能：
- 执行记录和报告生成
- 目录结构管理
- 元素标记绘制
- HTML 可视化报告
"""

from .types import (
    ScreenshotItem,
    UIContext,
    ServiceTaskInfo,
    ServiceDump,
    ServiceError,
    ExecutionRecorderItem,
    ExecutionTask,
    ExecutionDump,
    GroupedActionDump,
    PlanningAction,
    PlanningAIResponse,
)

from .dump import (
    ExecutionRecorder,
    SessionRecorder,
    GroupedExecutionRecorder,
    ServiceDumpBuilder,
    create_execution_recorder,
    create_session_recorder,
    create_grouped_recorder,
)

from .run_manager import (
    MidsceneRunManager,
    get_default_run_manager,
)

from .element_marker import (
    ElementMarker,
    MarkerStyle,
    ActionMarker,
    get_default_marker,
)

from .report_generator import (
    HTMLReportGenerator,
    ReportSession,
    ReportStep,
    get_default_report_generator,
)

from .js_report_generator import (
    JSCompatibleReportGenerator,
    GroupedActionDump,
    ExecutionDump as JSExecutionDump,
    ExecutionTask as JSExecutionTask,
    MatchedElement,
    AIUsage,
    TaskTiming,
    get_js_report_generator,
)

from .logging_system import (
    MidsceneLogManager,
    MidsceneFormatter,
    get_log_manager,
    reset_log_manager,
)


__all__ = [
    # Types
    "ScreenshotItem",
    "UIContext",
    "ServiceTaskInfo",
    "ServiceDump",
    "ServiceError",
    "ExecutionRecorderItem",
    "ExecutionTask",
    "ExecutionDump",
    "GroupedActionDump",
    "PlanningAction",
    "PlanningAIResponse",
    # Dump / Recording
    "ExecutionRecorder",
    "SessionRecorder",
    "GroupedExecutionRecorder",
    "ServiceDumpBuilder",
    "create_execution_recorder",
    "create_session_recorder",
    "create_grouped_recorder",
    # Run Manager
    "MidsceneRunManager",
    "get_default_run_manager",
    # Element Marker
    "ElementMarker",
    "MarkerStyle",
    "ActionMarker",
    "get_default_marker",
    # Report Generator
    "HTMLReportGenerator",
    "ReportSession",
    "ReportStep",
    "get_default_report_generator",
]
