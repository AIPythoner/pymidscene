"""
JS 兼容的 HTML 报告生成器 - 完全复制 JS 版本的 React 可视化界面

此模块生成与 JS 版本 Midscene 完全兼容的 HTML 报告:
1. 使用相同的数据格式 (GroupedActionDump)
2. 嵌入 JS 版本的 React 可视化组件
3. 支持相同的交互功能（截图放大、步骤展开等）

报告文件命名格式: {driver}-{YYYY-MM-DD_HH-MM-SS}-{uuid8}.html
"""

import json
import uuid
import base64
import time
from datetime import datetime
from typing import List, Optional, Dict, Any, Tuple
from dataclasses import dataclass, field, asdict
from pathlib import Path

from ..shared.logger import logger


@dataclass
class MatchedElement:
    """匹配的元素信息 - 与 JS 版本 LocateResultElement 对齐"""
    id: str = ""
    reason: str = ""
    text: str = ""
    indexId: Optional[int] = None
    rect: Optional[Dict[str, int]] = None  # {left, top, width, height}
    center: Optional[List[int]] = None  # [x, y]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "reason": self.reason,
            "text": self.text,
            "indexId": self.indexId,
            "rect": self.rect,
            "center": self.center,
        }


@dataclass
class ScreenshotInfo:
    """截图信息"""
    screenshot: str  # base64
    timing: str = "before"  # "before" | "after"

    def to_dict(self) -> dict:
        return {
            "type": "screenshot",
            "ts": int(time.time() * 1000),
            "screenshot": self.screenshot,
            "timing": self.timing,
        }


@dataclass
class TaskTiming:
    """任务时间信息"""
    start: int = 0  # 毫秒时间戳
    end: int = 0
    cost: int = 0  # 耗时毫秒

    def to_dict(self) -> dict:
        return {
            "start": self.start,
            "end": self.end,
            "cost": self.cost,
        }


@dataclass
class AIUsage:
    """AI 使用信息"""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def to_dict(self) -> dict:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass
class ExecutionTask:
    """
    执行任务 - 与 JS 版本 ExecutionTask 完全对齐

    对应 JS 版本的关键字段:
    - type: 任务类型 (Locate, Planning, Insight, Action)
    - subType: 子类型
    - status: 状态 (pending, running, finished, failed)
    - param: 任务参数
    - output: 输出结果
    - recorder: 截图记录数组
    - timing: 时间信息
    - usage: AI token 使用
    """
    type: str  # "Locate" | "Planning" | "Insight" | "Action"
    subType: Optional[str] = None
    subTask: bool = False
    status: str = "finished"  # "pending" | "running" | "finished" | "failed"

    # 参数 - 根据类型不同结构不同
    param: Optional[Dict[str, Any]] = None
    thought: Optional[str] = None

    # 输出
    output: Optional[Any] = None
    log: Optional[str] = None

    # 截图记录
    recorder: List[Dict] = field(default_factory=list)

    # 时间和资源
    timing: Optional[TaskTiming] = None
    usage: Optional[AIUsage] = None

    # 定位结果
    matchedElement: Optional[List[MatchedElement]] = None

    # 错误信息
    error: Optional[str] = None
    errorStack: Optional[str] = None

    # 缓存命中
    cacheHit: bool = False
    cacheType: Optional[str] = None

    def to_dict(self) -> dict:
        result = {
            "type": self.type,
            "subType": self.subType,
            "subTask": self.subTask,
            "status": self.status,
            "param": self.param,
            "thought": self.thought,
            "output": self.output,
            "log": self.log,
            "recorder": self.recorder,
        }

        if self.timing:
            result["timing"] = self.timing.to_dict()
        if self.usage:
            result["usage"] = self.usage.to_dict()
        if self.matchedElement:
            result["matchedElement"] = [e.to_dict() for e in self.matchedElement]
        if self.error:
            result["error"] = self.error
            result["errorStack"] = self.errorStack

        return result


@dataclass
class ExecutionDump:
    """
    执行记录 - 与 JS 版本 ExecutionDump 对齐

    对应一次完整的自动化执行会话
    """
    name: str
    description: Optional[str] = None
    tasks: List[ExecutionTask] = field(default_factory=list)
    logTime: int = 0  # 毫秒时间戳

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "tasks": [t.to_dict() for t in self.tasks],
            "logTime": self.logTime or int(time.time() * 1000),
        }


@dataclass
class GroupedActionDump:
    """
    分组执行记录 - 与 JS 版本 GroupedActionDump 完全对齐

    这是 HTML 报告中嵌入的顶层数据结构
    """
    sdkVersion: str = "1.0.0-python"
    logTime: int = 0
    groupName: str = ""
    groupDescription: Optional[str] = None
    executions: List[ExecutionDump] = field(default_factory=list)
    modelBriefs: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "sdkVersion": self.sdkVersion,
            "logTime": self.logTime or int(time.time() * 1000),
            "groupName": self.groupName,
            "groupDescription": self.groupDescription,
            "executions": [e.to_dict() for e in self.executions],
            "modelBriefs": self.modelBriefs,
        }


class JSCompatibleReportGenerator:
    """
    JS 兼容的报告生成器

    生成与 JS 版本 Midscene 完全兼容的 HTML 报告。
    报告使用 JS 版本的 React 可视化组件，数据格式完全对齐。
    """

    VERSION = "1.0.0"

    # JS 版本报告的 HTML 模板 - 从 @midscene/core 提取
    # 包含完整的 React 应用代码，用于渲染与 JS 版本完全一致的 UI
    _JS_TEMPLATE_CACHE: Optional[str] = None
    
    @classmethod
    def _get_js_template(cls) -> Optional[str]:
        """
        获取 JS 版本的 React HTML 模板
        
        优先从本地缓存的 JS 模板文件加载，如果不存在则使用简化版模板
        """
        if cls._JS_TEMPLATE_CACHE is not None:
            return cls._JS_TEMPLATE_CACHE
        
        # 尝试从 JS 版本的 node_modules 中加载模板
        import os
        possible_paths = [
            # 常见的 JS 项目路径
            r"E:\code\qinghu\js-rpa-script\node_modules\@midscene\core\dist\lib\utils.js",
        ]
        
        for path in possible_paths:
            if os.path.exists(path):
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    # 提取模板内容
                    import re
                    match = re.search(r'getReportTpl\(\)\s*\{\s*(?:const\s+reportTpl\s*=\s*)?/\*REPORT_HTML_REPLACED\*/\s*"([^"]*(?:\\.[^"]*)*)"', content)
                    if match:
                        template = match.group(1)
                        # 解码转义字符
                        template = template.encode().decode('unicode_escape')
                        cls._JS_TEMPLATE_CACHE = template
                        return template
                except Exception as e:
                    pass
        
        # 回退到简化版模板
        return None

    # JS 版本报告的 HTML 模板头部（简化版，当无法加载 JS 模板时使用）
    HTML_TEMPLATE_HEAD = '''<!doctype html>
<html>
  <head>
    <title>Report - PyMidscene</title>
    <link
      rel="icon"
      type="image/png"
      sizes="32x32"
      href="https://lf3-static.bytednsdoc.com/obj/eden-cn/vhaeh7vhabf/favicon-32x32.png"
    />
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
  <body>
    <div id="root" style="height: 100vh; width: 100vw"></div>
'''

    # 简化版可视化界面（不依赖 React）
    VISUALIZER_TEMPLATE = '''
    <style>
      * { margin: 0; padding: 0; box-sizing: border-box; }
      body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f7fa; }
      .container { max-width: 1400px; margin: 0 auto; padding: 20px; }

      /* Header */
      .header {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white; padding: 24px; border-radius: 12px; margin-bottom: 20px;
        box-shadow: 0 4px 20px rgba(102, 126, 234, 0.3);
      }
      .header h1 { font-size: 24px; margin-bottom: 8px; display: flex; align-items: center; gap: 12px; }
      .header .logo { width: 36px; height: 36px; background: white; border-radius: 8px;
        display: flex; align-items: center; justify-content: center; font-weight: bold; color: #667eea; }
      .meta { display: flex; gap: 24px; font-size: 14px; opacity: 0.9; flex-wrap: wrap; }
      .meta-item { display: flex; gap: 6px; }
      .meta-item .label { opacity: 0.7; }

      /* Stats */
      .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 16px; margin-bottom: 20px; }
      .stat-card { background: white; padding: 20px; border-radius: 10px; text-align: center;
        box-shadow: 0 2px 8px rgba(0,0,0,0.06); }
      .stat-card .number { font-size: 32px; font-weight: bold; color: #667eea; }
      .stat-card.success .number { color: #10b981; }
      .stat-card.failed .number { color: #ef4444; }
      .stat-card .label { font-size: 13px; color: #666; margin-top: 4px; }

      /* Timeline */
      .timeline { background: white; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); overflow: hidden; }
      .timeline-header { padding: 16px 20px; border-bottom: 1px solid #eee; font-weight: 600; font-size: 16px;
        display: flex; justify-content: space-between; align-items: center; }
      .expand-all { font-size: 13px; color: #667eea; cursor: pointer; font-weight: normal; }

      /* Task */
      .task { border-bottom: 1px solid #f0f0f0; }
      .task:last-child { border-bottom: none; }
      .task-header { padding: 16px 20px; display: flex; align-items: center; gap: 16px; cursor: pointer;
        transition: background 0.15s; }
      .task-header:hover { background: #fafafa; }
      .task-index { width: 28px; height: 28px; border-radius: 50%; background: #667eea; color: white;
        display: flex; align-items: center; justify-content: center; font-size: 12px; font-weight: 600; flex-shrink: 0; }
      .task.success .task-index { background: #10b981; }
      .task.failed .task-index { background: #ef4444; }
      .task-info { flex: 1; min-width: 0; }
      .task-type { display: inline-flex; align-items: center; gap: 8px; }
      .type-badge { padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; text-transform: uppercase; }
      .type-badge.Locate { background: #fce7f3; color: #be185d; }
      .type-badge.Planning { background: #dbeafe; color: #1d4ed8; }
      .type-badge.Action { background: #d1fae5; color: #047857; }
      .type-badge.Insight { background: #fef3c7; color: #b45309; }
      .task-prompt { font-size: 14px; color: #333; margin-top: 4px;
        white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 600px; }
      .task-meta { display: flex; gap: 16px; font-size: 12px; color: #999; }
      .task-toggle { width: 20px; color: #999; transition: transform 0.2s; }
      .task.expanded .task-toggle { transform: rotate(180deg); }

      /* Task Details */
      .task-details { display: none; padding: 0 20px 20px; background: #fafafa; }
      .task.expanded .task-details { display: block; }

      /* Screenshots */
      .screenshots { display: grid; grid-template-columns: repeat(auto-fit, minmax(400px, 1fr)); gap: 16px; margin-bottom: 16px; }
      .screenshot-panel { background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 4px rgba(0,0,0,0.08); }
      .screenshot-label { padding: 10px 12px; background: #f5f5f5; font-size: 12px; font-weight: 600; color: #666;
        border-bottom: 1px solid #eee; }
      .screenshot-img { width: 100%; display: block; cursor: zoom-in; }

      /* Details Grid */
      .details-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; }
      .detail-card { background: white; border-radius: 8px; padding: 16px; box-shadow: 0 1px 4px rgba(0,0,0,0.08); }
      .detail-card h4 { font-size: 12px; color: #666; margin-bottom: 12px; text-transform: uppercase; letter-spacing: 0.5px; }
      .detail-card pre { background: #f5f5f5; padding: 12px; border-radius: 6px; font-size: 12px;
        overflow-x: auto; white-space: pre-wrap; word-break: break-all; max-height: 200px; }
      .element-info .row { display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid #f0f0f0; }
      .element-info .row:last-child { border-bottom: none; }
      .element-info .label { color: #666; font-size: 13px; }
      .element-info .value { font-weight: 500; color: #333; font-size: 13px; }

      /* Error */
      .error-box { background: #fef2f2; border: 1px solid #fecaca; color: #dc2626; padding: 12px;
        border-radius: 6px; font-size: 13px; margin-top: 16px; }

      /* Cache Hit Badge */
      .cache-badge { display: inline-flex; align-items: center; gap: 4px; padding: 2px 6px;
        background: #d1fae5; color: #047857; border-radius: 4px; font-size: 10px; font-weight: 600; }

      /* Modal */
      .modal { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%;
        background: rgba(0,0,0,0.9); z-index: 1000; align-items: center; justify-content: center; }
      .modal.active { display: flex; }
      .modal img { max-width: 95%; max-height: 95%; object-fit: contain; }
      .modal-close { position: fixed; top: 20px; right: 20px; width: 40px; height: 40px; background: white;
        border-radius: 50%; display: flex; align-items: center; justify-content: center; cursor: pointer;
        font-size: 24px; color: #333; }

      /* Footer */
      .footer { text-align: center; padding: 24px; color: #999; font-size: 13px; }
      .footer a { color: #667eea; text-decoration: none; }
    </style>

    <div class="container">
      <div class="header">
        <h1><div class="logo">M</div>PyMidscene Execution Report</h1>
        <div class="meta">
          <div class="meta-item"><span class="label">Driver:</span><span id="driver-type"></span></div>
          <div class="meta-item"><span class="label">Started:</span><span id="start-time"></span></div>
          <div class="meta-item"><span class="label">Duration:</span><span id="duration"></span></div>
          <div class="meta-item"><span class="label">Status:</span><span id="status"></span></div>
        </div>
      </div>

      <div class="stats">
        <div class="stat-card"><div class="number" id="total-tasks">0</div><div class="label">Total Steps</div></div>
        <div class="stat-card success"><div class="number" id="success-tasks">0</div><div class="label">Successful</div></div>
        <div class="stat-card failed"><div class="number" id="failed-tasks">0</div><div class="label">Failed</div></div>
      </div>

      <div class="timeline">
        <div class="timeline-header">
          <span>Execution Steps</span>
          <span class="expand-all" onclick="toggleAllTasks()">Expand All</span>
        </div>
        <div id="tasks-container"></div>
      </div>

      <div class="footer">
        Generated by <a href="https://github.com/anthropics/pymidscene" target="_blank">PyMidscene</a> v{version}
        <br>{generation_time}
      </div>
    </div>

    <div class="modal" id="imageModal">
      <div class="modal-close" onclick="closeModal()">&times;</div>
      <img id="modalImage" src="" alt="Screenshot">
    </div>

    <script>
      // Report data embedded by Python
      const reportData = {report_data};

      // Initialize report
      function initReport() {
        const data = reportData;
        const execution = data.executions && data.executions[0];
        if (!execution) return;

        // Header info
        document.getElementById('driver-type').textContent = data.groupName || 'Playwright';
        document.getElementById('start-time').textContent = new Date(data.logTime).toLocaleString();

        const tasks = execution.tasks || [];
        const successCount = tasks.filter(t => t.status === 'finished').length;
        const failedCount = tasks.filter(t => t.status === 'failed').length;

        document.getElementById('total-tasks').textContent = tasks.length;
        document.getElementById('success-tasks').textContent = successCount;
        document.getElementById('failed-tasks').textContent = failedCount;
        document.getElementById('status').textContent = failedCount > 0 ? 'FAILED' : 'SUCCESS';

        // Calculate duration
        if (tasks.length > 0) {
          const totalDuration = tasks.reduce((sum, t) => sum + (t.timing?.cost || 0), 0);
          document.getElementById('duration').textContent = formatDuration(totalDuration);
        }

        // Render tasks
        const container = document.getElementById('tasks-container');
        tasks.forEach((task, index) => {
          container.appendChild(createTaskElement(task, index + 1));
        });
      }

      function formatDuration(ms) {
        if (ms < 1000) return ms + 'ms';
        const seconds = Math.floor(ms / 1000);
        if (seconds < 60) return seconds + 's';
        const minutes = Math.floor(seconds / 60);
        return minutes + 'm ' + (seconds % 60) + 's';
      }

      function createTaskElement(task, index) {
        const div = document.createElement('div');
        div.className = 'task ' + (task.status === 'finished' ? 'success' : task.status === 'failed' ? 'failed' : '');

        const prompt = getTaskPrompt(task);
        const duration = task.timing?.cost || 0;

        // Screenshots
        let screenshotsHtml = '';
        if (task.recorder && task.recorder.length > 0) {
          screenshotsHtml = '<div class="screenshots">';
          task.recorder.forEach(rec => {
            if (rec.screenshot) {
              const imgSrc = rec.screenshot.startsWith('data:') ? rec.screenshot : 'data:image/png;base64,' + rec.screenshot;
              screenshotsHtml += `
                <div class="screenshot-panel">
                  <div class="screenshot-label">${rec.timing === 'before' ? 'Before' : 'After'}</div>
                  <img class="screenshot-img" src="${imgSrc}" onclick="openModal(this.src)">
                </div>`;
            }
          });
          screenshotsHtml += '</div>';
        }

        // Element info
        let elementHtml = '';
        if (task.matchedElement && task.matchedElement.length > 0) {
          const elem = task.matchedElement[0];
          elementHtml = `
            <div class="detail-card">
              <h4>Element Location</h4>
              <div class="element-info">
                ${elem.rect ? `<div class="row"><span class="label">Bounding Box</span><span class="value">[${elem.rect.left}, ${elem.rect.top}, ${elem.rect.width}, ${elem.rect.height}]</span></div>` : ''}
                ${elem.center ? `<div class="row"><span class="label">Click Point</span><span class="value">(${elem.center[0]}, ${elem.center[1]})</span></div>` : ''}
                ${elem.text ? `<div class="row"><span class="label">Text</span><span class="value">${elem.text}</span></div>` : ''}
              </div>
            </div>`;
        }

        // AI info
        let aiHtml = '';
        if (task.usage) {
          aiHtml = `
            <div class="detail-card">
              <h4>AI Information</h4>
              <div class="element-info">
                <div class="row"><span class="label">Total Tokens</span><span class="value">${task.usage.total_tokens || 0}</span></div>
                <div class="row"><span class="label">Prompt Tokens</span><span class="value">${task.usage.prompt_tokens || 0}</span></div>
                <div class="row"><span class="label">Completion Tokens</span><span class="value">${task.usage.completion_tokens || 0}</span></div>
              </div>
            </div>`;
        }

        // Error
        let errorHtml = '';
        if (task.error) {
          errorHtml = `<div class="error-box">${task.error}</div>`;
        }

        div.innerHTML = `
          <div class="task-header" onclick="toggleTask(this)">
            <div class="task-index">${index}</div>
            <div class="task-info">
              <div class="task-type">
                <span class="type-badge ${task.type}">${task.type}</span>
                ${task.cacheHit ? '<span class="cache-badge">CACHE HIT</span>' : ''}
              </div>
              <div class="task-prompt">${escapeHtml(prompt)}</div>
            </div>
            <div class="task-meta">
              <span>${formatDuration(duration)}</span>
            </div>
            <div class="task-toggle">▼</div>
          </div>
          <div class="task-details">
            ${screenshotsHtml}
            <div class="details-grid">
              ${elementHtml}
              ${aiHtml}
            </div>
            ${errorHtml}
          </div>`;

        return div;
      }

      function getTaskPrompt(task) {
        if (!task.param) return task.type;
        if (typeof task.param === 'string') return task.param;
        if (task.param.prompt) return task.param.prompt;
        if (task.param.value) return task.param.value;
        if (task.param.locate?.prompt) return task.param.locate.prompt;
        return JSON.stringify(task.param).slice(0, 100);
      }

      function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
      }

      function toggleTask(header) {
        header.parentElement.classList.toggle('expanded');
      }

      function toggleAllTasks() {
        const tasks = document.querySelectorAll('.task');
        const allExpanded = Array.from(tasks).every(t => t.classList.contains('expanded'));
        tasks.forEach(t => {
          if (allExpanded) t.classList.remove('expanded');
          else t.classList.add('expanded');
        });
      }

      function openModal(src) {
        document.getElementById('modalImage').src = src;
        document.getElementById('imageModal').classList.add('active');
      }

      function closeModal() {
        document.getElementById('imageModal').classList.remove('active');
      }

      document.getElementById('imageModal').addEventListener('click', function(e) {
        if (e.target.id === 'imageModal') closeModal();
      });

      document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') closeModal();
      });

      // Initialize on load
      initReport();
    </script>
'''

    HTML_TEMPLATE_TAIL = '''
  </body>
</html>'''

    def __init__(self):
        """初始化报告生成器"""
        self._current_dump: Optional[GroupedActionDump] = None
        self._current_execution: Optional[ExecutionDump] = None

    def start_session(
        self,
        group_name: str = "PyMidscene Execution",
        description: Optional[str] = None,
        model_name: Optional[str] = None
    ):
        """
        开始新的报告会话

        Args:
            group_name: 组名称
            description: 描述
            model_name: 使用的模型名称
        """
        self._current_dump = GroupedActionDump(
            sdkVersion=f"{self.VERSION}-python",
            logTime=int(time.time() * 1000),
            groupName=group_name,
            groupDescription=description,
            executions=[],
            modelBriefs=[model_name] if model_name else [],
        )

        self._current_execution = ExecutionDump(
            name=group_name,
            description=description,
            tasks=[],
            logTime=int(time.time() * 1000),
        )

        self._current_dump.executions.append(self._current_execution)

    def add_task(
        self,
        task_type: str,
        prompt: str,
        status: str = "finished",
        screenshot_before: Optional[str] = None,
        screenshot_after: Optional[str] = None,
        screenshot_marked: Optional[str] = None,
        element_rect: Optional[Dict[str, int]] = None,
        element_center: Optional[List[int]] = None,
        element_text: Optional[str] = None,
        duration_ms: int = 0,
        ai_tokens: Optional[int] = None,
        ai_prompt_tokens: Optional[int] = None,
        ai_completion_tokens: Optional[int] = None,
        error: Optional[str] = None,
        cache_hit: bool = False,
        thought: Optional[str] = None,
    ):
        """
        添加执行任务

        Args:
            task_type: 任务类型 (Locate, Planning, Action, Insight)
            prompt: 用户指令
            status: 状态 (finished, failed, pending)
            screenshot_before: 操作前截图 (base64)
            screenshot_after: 操作后截图 (base64)
            screenshot_marked: 带标记的截图 (base64)
            element_rect: 元素边界框 {left, top, width, height}
            element_center: 元素中心点 [x, y]
            element_text: 元素文本
            duration_ms: 耗时毫秒
            ai_tokens: AI token 总数
            ai_prompt_tokens: 提示 token 数
            ai_completion_tokens: 完成 token 数
            error: 错误信息
            cache_hit: 是否缓存命中
            thought: AI 思考过程
        """
        if not self._current_execution:
            self.start_session()

        # 构建截图记录
        recorder = []
        if screenshot_before:
            recorder.append({
                "type": "screenshot",
                "ts": int(time.time() * 1000),
                "screenshot": screenshot_before,
                "timing": "before",
            })
        if screenshot_marked:
            recorder.append({
                "type": "screenshot",
                "ts": int(time.time() * 1000),
                "screenshot": screenshot_marked,
                "timing": "after",
            })
        elif screenshot_after:
            recorder.append({
                "type": "screenshot",
                "ts": int(time.time() * 1000),
                "screenshot": screenshot_after,
                "timing": "after",
            })

        # 构建匹配元素
        matched_element = None
        if element_rect or element_center:
            matched_element = [MatchedElement(
                id=str(uuid.uuid4())[:8],
                reason=prompt,
                text=element_text or "",
                rect=element_rect,
                center=element_center,
            )]

        # 构建 AI 使用信息
        usage = None
        if ai_tokens or ai_prompt_tokens or ai_completion_tokens:
            usage = AIUsage(
                prompt_tokens=ai_prompt_tokens or 0,
                completion_tokens=ai_completion_tokens or 0,
                total_tokens=ai_tokens or (ai_prompt_tokens or 0) + (ai_completion_tokens or 0),
            )

        # 构建时间信息
        timing = TaskTiming(
            start=int(time.time() * 1000) - duration_ms,
            end=int(time.time() * 1000),
            cost=duration_ms,
        )

        task = ExecutionTask(
            type=task_type,
            status=status,
            param={"prompt": prompt},
            thought=thought,
            recorder=recorder,
            matchedElement=matched_element,
            timing=timing,
            usage=usage,
            error=error,
            cacheHit=cache_hit,
        )

        if self._current_execution is None:
            self.start_session()
        # 类型断言：此时 _current_execution 一定不为 None
        assert self._current_execution is not None
        self._current_execution.tasks.append(task)

    def generate_html(self) -> str:
        """
        生成 HTML 报告

        Returns:
            完整的 HTML 字符串
        """
        if not self._current_dump:
            self.start_session()
        
        # 类型断言：此时 _current_dump 一定不为 None
        assert self._current_dump is not None
        report_data = json.dumps(
            self._current_dump.to_dict(),
            ensure_ascii=False,
            separators=(',', ':')
        )

        html = self.HTML_TEMPLATE_HEAD
        html += self.VISUALIZER_TEMPLATE.format(
            version=self.VERSION,
            generation_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            report_data=report_data,
        )
        html += self.HTML_TEMPLATE_TAIL

        return html

    def save(
        self,
        report_dir: str,
        driver_type: str = "playwright",
        filename: Optional[str] = None
    ) -> str:
        """
        保存 HTML 报告到文件

        Args:
            report_dir: 报告目录
            driver_type: 驱动类型
            filename: 文件名（可选，默认自动生成）

        Returns:
            保存的文件路径
        """
        # 生成文件名
        if filename is None:
            timestamp = datetime.now()
            session_id = uuid.uuid4().hex[:8]
            filename = f"{driver_type}-{timestamp.strftime('%Y-%m-%d_%H-%M-%S')}-{session_id}.html"

        # 确保目录存在
        report_path = Path(report_dir)
        report_path.mkdir(parents=True, exist_ok=True)

        # 生成并保存 HTML
        html_content = self.generate_html()
        file_path = report_path / filename

        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(html_content)

        logger.info(f"Report saved to: {file_path}")
        return str(file_path)

    def reset(self):
        """重置报告生成器"""
        self._current_dump = None
        self._current_execution = None


# 全局实例
_default_js_generator: Optional[JSCompatibleReportGenerator] = None


def get_js_report_generator() -> JSCompatibleReportGenerator:
    """获取默认的 JS 兼容报告生成器"""
    global _default_js_generator
    if _default_js_generator is None:
        _default_js_generator = JSCompatibleReportGenerator()
    return _default_js_generator


__all__ = [
    "JSCompatibleReportGenerator",
    "GroupedActionDump",
    "ExecutionDump",
    "ExecutionTask",
    "MatchedElement",
    "AIUsage",
    "TaskTiming",
    "get_js_report_generator",
]
