"""
HTML 报告生成器 - 生成与 JS 版本对齐的可视化 HTML 报告

生成自包含的 HTML 文件，包含：
- 执行步骤时间线
- 截图对比视图（Before/After）
- 元素定位标记（带边界框和点击点）
- AI 响应详情
- 与 JS 版本 Midscene Visualizer 兼容的数据格式

报告文件命名格式: {driver}-{YYYY-MM-DD_HH-MM-SS}-{uuid8}.html
"""

import json
import uuid
import base64
from datetime import datetime
from typing import List, Optional, Dict, Any, Tuple
from dataclasses import dataclass, field, asdict
from pathlib import Path

from ..shared.logger import logger


@dataclass
class ReportStep:
    """
    报告中的单个步骤 - 与 JS 版本 ExecutionTask 对齐

    对应 JS 版本的字段:
    - type: 操作类型
    - param: 操作参数
    - thought: AI 思考过程
    - status: 执行状态
    - timing: 时间信息
    - recorder: 截图记录
    """
    step_id: str
    step_index: int
    action_type: str  # 'Tap', 'Input', 'Scroll', 'Assert', 'Query', 'Locate' (与JS对齐用大写)
    prompt: str
    timestamp: str
    duration_ms: int
    status: str  # 'success', 'failed', 'pending'

    # 截图 - 对应 JS 版本的 recorder 数组
    screenshot_before: Optional[str] = None  # base64
    screenshot_after: Optional[str] = None  # base64
    screenshot_marked: Optional[str] = None  # 带标记的截图（元素边框+点击位置）

    # 元素定位信息 - 对应 JS 版本的 matchedElement
    element_bbox: Optional[List[int]] = None  # [x1, y1, x2, y2]
    element_center: Optional[List[int]] = None  # [x, y] 点击位置
    element_description: Optional[str] = None
    element_xpath: Optional[str] = None  # XPath（从缓存获取）

    # AI 信息 - 对应 JS 版本的 usage 和 taskInfo
    ai_model: Optional[str] = None
    ai_tokens: Optional[int] = None
    ai_response: Optional[str] = None
    ai_reasoning: Optional[str] = None
    ai_raw_response: Optional[str] = None  # 原始响应

    # 缓存信息
    cache_hit: bool = False
    cache_type: Optional[str] = None  # 'plan', 'locate'

    # 错误信息
    error_message: Optional[str] = None

    def to_dict(self) -> dict:
        """转换为与 JS 版本兼容的字典格式"""
        result = asdict(self)
        # 转换为 camelCase 以与 JS 版本对齐
        return {
            "stepId": result["step_id"],
            "stepIndex": result["step_index"],
            "type": result["action_type"],
            "param": {"prompt": result["prompt"]},
            "timestamp": result["timestamp"],
            "durationMs": result["duration_ms"],
            "status": result["status"],
            "screenshotBefore": result["screenshot_before"],
            "screenshotAfter": result["screenshot_after"],
            "screenshotMarked": result["screenshot_marked"],
            "matchedElement": {
                "bbox": result["element_bbox"],
                "center": result["element_center"],
                "description": result["element_description"],
                "xpath": result["element_xpath"],
            } if result["element_bbox"] else None,
            "aiInfo": {
                "model": result["ai_model"],
                "tokens": result["ai_tokens"],
                "response": result["ai_response"],
                "reasoning": result["ai_reasoning"],
            } if result["ai_model"] else None,
            "cacheHit": result["cache_hit"],
            "cacheType": result["cache_type"],
            "errorMessage": result["error_message"],
        }


@dataclass
class ReportSession:
    """
    报告会话 - 与 JS 版本 GroupedActionDump 对齐

    对应 JS 版本的字段结构，确保生成的 HTML 报告可以被 JS 版 Visualizer 解析
    """
    session_id: str
    driver_type: str  # 'playwright', 'selenium', 'appium'
    start_time: str
    end_time: Optional[str] = None
    status: str = "running"  # 'running', 'success', 'failed'
    total_steps: int = 0
    success_steps: int = 0
    failed_steps: int = 0
    steps: List[ReportStep] = field(default_factory=list)

    # 元数据
    page_url: Optional[str] = None
    page_title: Optional[str] = None
    viewport_size: Optional[Dict[str, int]] = None
    pymidscene_version: str = "1.0.0"

    # 与 JS 版本对齐的额外字段
    group_name: Optional[str] = None
    group_description: Optional[str] = None
    model_briefs: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """转换为与 JS 版本兼容的字典格式"""
        result = {
            "sdkVersion": self.pymidscene_version,
            "logTime": datetime.fromisoformat(self.start_time).timestamp() * 1000 if self.start_time else 0,
            "groupName": self.group_name or f"Session {self.session_id[:8]}",
            "groupDescription": self.group_description,
            "modelBriefs": self.model_briefs,
            "executions": [{
                "name": f"{self.driver_type} Execution",
                "description": f"Page: {self.page_url or 'N/A'}",
                "tasks": [step.to_dict() for step in self.steps],
                "status": self.status,
                "startTime": self.start_time,
                "endTime": self.end_time,
            }],
            # 额外的元数据
            "meta": {
                "sessionId": self.session_id,
                "driverType": self.driver_type,
                "pageUrl": self.page_url,
                "pageTitle": self.page_title,
                "viewportSize": self.viewport_size,
                "totalSteps": self.total_steps,
                "successSteps": self.success_steps,
                "failedSteps": self.failed_steps,
            }
        }
        return result


class HTMLReportGenerator:
    """
    HTML 报告生成器

    生成与 JS 版本 Midscene 对齐的可视化 HTML 报告。
    报告是自包含的，所有 CSS、JS 和图片都内嵌在 HTML 中。
    """

    VERSION = "1.0.0"

    def __init__(self):
        """初始化报告生成器"""
        pass

    def _get_html_template(self) -> str:
        """
        获取 HTML 模板 - 与 JS 版本 Midscene Report 对齐

        模板结构:
        1. 嵌入 window.__MIDSCENE_REPORT_DATA__ 数据（与 JS 版本兼容）
        2. 自包含的 CSS 样式
        3. 交互式步骤时间线
        4. 截图查看器（支持放大）
        5. 元素定位可视化
        """
        return '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Report - PyMidscene</title>
    <link rel="icon" type="image/png" sizes="32x32" href="https://lf3-static.bytednsdoc.com/obj/eden-cn/vhaeh7vhabf/favicon-32x32.png" />
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: #f5f5f5;
            color: #333;
            line-height: 1.6;
        }}

        .container {{
            max-width: 1400px;
            margin: 0 auto;
            padding: 20px;
        }}

        /* Header */
        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            border-radius: 12px;
            margin-bottom: 20px;
            box-shadow: 0 4px 15px rgba(102, 126, 234, 0.4);
        }}

        .header h1 {{
            font-size: 28px;
            margin-bottom: 15px;
            display: flex;
            align-items: center;
            gap: 10px;
        }}

        .header .logo {{
            width: 40px;
            height: 40px;
            background: white;
            border-radius: 8px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: bold;
            color: #667eea;
        }}

        .meta-info {{
            display: flex;
            flex-wrap: wrap;
            gap: 20px;
            font-size: 14px;
            opacity: 0.9;
        }}

        .meta-item {{
            display: flex;
            align-items: center;
            gap: 6px;
        }}

        .meta-item .label {{
            opacity: 0.7;
        }}

        /* Stats */
        .stats {{
            display: flex;
            gap: 15px;
            margin-bottom: 20px;
        }}

        .stat-card {{
            background: white;
            padding: 20px 25px;
            border-radius: 10px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
            flex: 1;
            text-align: center;
        }}

        .stat-card .number {{
            font-size: 32px;
            font-weight: bold;
            color: #667eea;
        }}

        .stat-card.success .number {{
            color: #10b981;
        }}

        .stat-card.failed .number {{
            color: #ef4444;
        }}

        .stat-card .label {{
            font-size: 13px;
            color: #666;
            margin-top: 5px;
        }}

        /* Timeline */
        .timeline {{
            background: white;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
            overflow: hidden;
        }}

        .timeline-header {{
            padding: 20px;
            border-bottom: 1px solid #eee;
            font-size: 18px;
            font-weight: 600;
        }}

        .step {{
            border-bottom: 1px solid #f0f0f0;
            transition: background 0.2s;
        }}

        .step:last-child {{
            border-bottom: none;
        }}

        .step:hover {{
            background: #fafafa;
        }}

        .step-header {{
            padding: 15px 20px;
            display: flex;
            align-items: center;
            gap: 15px;
            cursor: pointer;
            user-select: none;
        }}

        .step-index {{
            width: 32px;
            height: 32px;
            border-radius: 50%;
            background: #667eea;
            color: white;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: bold;
            font-size: 14px;
            flex-shrink: 0;
        }}

        .step.success .step-index {{
            background: #10b981;
        }}

        .step.failed .step-index {{
            background: #ef4444;
        }}

        .step-info {{
            flex: 1;
            min-width: 0;
        }}

        .step-action {{
            font-weight: 600;
            color: #333;
            display: flex;
            align-items: center;
            gap: 8px;
        }}

        .action-badge {{
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
        }}

        .action-badge.click {{
            background: #dbeafe;
            color: #1d4ed8;
        }}

        .action-badge.input {{
            background: #fef3c7;
            color: #b45309;
        }}

        .action-badge.assert {{
            background: #d1fae5;
            color: #047857;
        }}

        .action-badge.query {{
            background: #e0e7ff;
            color: #4338ca;
        }}

        .action-badge.locate {{
            background: #fce7f3;
            color: #be185d;
        }}

        .step-prompt {{
            font-size: 14px;
            color: #666;
            margin-top: 4px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}

        .step-meta {{
            display: flex;
            gap: 15px;
            font-size: 12px;
            color: #999;
        }}

        .step-toggle {{
            width: 24px;
            height: 24px;
            display: flex;
            align-items: center;
            justify-content: center;
            color: #999;
            transition: transform 0.2s;
        }}

        .step.expanded .step-toggle {{
            transform: rotate(180deg);
        }}

        /* Step Details */
        .step-details {{
            display: none;
            padding: 0 20px 20px;
            background: #fafafa;
        }}

        .step.expanded .step-details {{
            display: block;
        }}

        .screenshots {{
            display: flex;
            gap: 20px;
            margin-bottom: 20px;
        }}

        .screenshot-panel {{
            flex: 1;
            background: white;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 1px 4px rgba(0,0,0,0.1);
        }}

        .screenshot-label {{
            padding: 10px 15px;
            background: #f5f5f5;
            font-size: 13px;
            font-weight: 600;
            color: #666;
            border-bottom: 1px solid #eee;
        }}

        .screenshot-img {{
            width: 100%;
            display: block;
            cursor: zoom-in;
        }}

        .details-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 15px;
        }}

        .detail-card {{
            background: white;
            border-radius: 8px;
            padding: 15px;
            box-shadow: 0 1px 4px rgba(0,0,0,0.1);
        }}

        .detail-card h4 {{
            font-size: 13px;
            color: #666;
            margin-bottom: 10px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}

        .detail-card pre {{
            background: #f5f5f5;
            padding: 10px;
            border-radius: 4px;
            font-size: 12px;
            overflow-x: auto;
            white-space: pre-wrap;
            word-break: break-all;
        }}

        .element-info {{
            font-size: 13px;
        }}

        .element-info .row {{
            display: flex;
            justify-content: space-between;
            padding: 5px 0;
            border-bottom: 1px solid #f0f0f0;
        }}

        .element-info .row:last-child {{
            border-bottom: none;
        }}

        .element-info .label {{
            color: #666;
        }}

        .element-info .value {{
            font-weight: 500;
            color: #333;
        }}

        .error-message {{
            background: #fef2f2;
            border: 1px solid #fecaca;
            color: #dc2626;
            padding: 12px;
            border-radius: 6px;
            font-size: 13px;
            margin-top: 15px;
        }}

        /* Modal */
        .modal {{
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0,0,0,0.9);
            z-index: 1000;
            align-items: center;
            justify-content: center;
        }}

        .modal.active {{
            display: flex;
        }}

        .modal img {{
            max-width: 95%;
            max-height: 95%;
            object-fit: contain;
        }}

        .modal-close {{
            position: fixed;
            top: 20px;
            right: 20px;
            width: 40px;
            height: 40px;
            background: white;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            font-size: 24px;
            color: #333;
        }}

        /* Footer */
        .footer {{
            text-align: center;
            padding: 30px;
            color: #999;
            font-size: 13px;
        }}

        .footer a {{
            color: #667eea;
            text-decoration: none;
        }}

        /* ========== Timeline Visualization ========== */
        .timeline-visual {{
            background: white;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
            padding: 20px;
            margin-bottom: 20px;
        }}

        .timeline-visual-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
        }}

        .timeline-visual-title {{
            font-size: 18px;
            font-weight: 600;
            color: #333;
        }}

        .timeline-time-range {{
            font-size: 12px;
            color: #999;
        }}

        .timeline-bars {{
            display: flex;
            align-items: center;
            height: 40px;
            background: #f5f5f5;
            border-radius: 8px;
            overflow: hidden;
            position: relative;
            cursor: pointer;
        }}

        .timeline-bar {{
            height: 100%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 11px;
            color: white;
            font-weight: 600;
            transition: opacity 0.2s, transform 0.2s;
            position: relative;
            min-width: 20px;
        }}

        .timeline-bar:hover {{
            opacity: 0.9;
            transform: scaleY(1.1);
            z-index: 10;
        }}

        .timeline-bar.success {{
            background: linear-gradient(135deg, #10b981 0%, #059669 100%);
        }}

        .timeline-bar.failed {{
            background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%);
        }}

        .timeline-bar.pending {{
            background: linear-gradient(135deg, #667eea 0%, #5a67d8 100%);
        }}

        .timeline-bar.active {{
            box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.5);
            z-index: 20;
        }}

        .timeline-cursor {{
            position: absolute;
            top: 0;
            width: 3px;
            height: 100%;
            background: #333;
            z-index: 30;
            pointer-events: none;
            transition: left 0.1s ease-out;
        }}

        .timeline-cursor::after {{
            content: '';
            position: absolute;
            top: -5px;
            left: -4px;
            width: 11px;
            height: 11px;
            background: #333;
            border-radius: 50%;
        }}

        .timeline-tooltip {{
            position: absolute;
            bottom: 100%;
            left: 50%;
            transform: translateX(-50%);
            background: #333;
            color: white;
            padding: 6px 10px;
            border-radius: 4px;
            font-size: 11px;
            white-space: nowrap;
            opacity: 0;
            pointer-events: none;
            transition: opacity 0.2s;
            margin-bottom: 8px;
        }}

        .timeline-bar:hover .timeline-tooltip {{
            opacity: 1;
        }}

        /* ========== Playback Controls ========== */
        .playback-controls {{
            background: white;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
            padding: 20px;
            margin-bottom: 20px;
        }}

        .playback-main {{
            display: flex;
            align-items: center;
            gap: 20px;
        }}

        .playback-buttons {{
            display: flex;
            align-items: center;
            gap: 8px;
        }}

        .playback-btn {{
            width: 40px;
            height: 40px;
            border: none;
            border-radius: 50%;
            background: #f5f5f5;
            color: #333;
            font-size: 16px;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: all 0.2s;
        }}

        .playback-btn:hover {{
            background: #e5e5e5;
        }}

        .playback-btn.primary {{
            width: 50px;
            height: 50px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            font-size: 20px;
        }}

        .playback-btn.primary:hover {{
            transform: scale(1.05);
            box-shadow: 0 4px 15px rgba(102, 126, 234, 0.4);
        }}

        .playback-btn:disabled {{
            opacity: 0.5;
            cursor: not-allowed;
        }}

        .playback-progress {{
            flex: 1;
            display: flex;
            flex-direction: column;
            gap: 8px;
        }}

        .playback-progress-bar {{
            height: 6px;
            background: #e5e5e5;
            border-radius: 3px;
            overflow: hidden;
            cursor: pointer;
        }}

        .playback-progress-fill {{
            height: 100%;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            border-radius: 3px;
            transition: width 0.1s ease-out;
        }}

        .playback-info {{
            display: flex;
            justify-content: space-between;
            font-size: 12px;
            color: #666;
        }}

        .playback-step-info {{
            font-weight: 600;
        }}

        .playback-speed {{
            display: flex;
            align-items: center;
            gap: 8px;
        }}

        .playback-speed-label {{
            font-size: 12px;
            color: #666;
        }}

        .playback-speed-select {{
            padding: 6px 12px;
            border: 1px solid #ddd;
            border-radius: 6px;
            background: white;
            font-size: 12px;
            cursor: pointer;
        }}

        /* ========== Screenshot Player ========== */
        .screenshot-player {{
            background: white;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
            margin-bottom: 20px;
            overflow: hidden;
        }}

        .screenshot-player-header {{
            padding: 15px 20px;
            border-bottom: 1px solid #eee;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}

        .screenshot-player-title {{
            font-size: 16px;
            font-weight: 600;
            color: #333;
        }}

        .screenshot-player-step {{
            font-size: 14px;
            color: #666;
        }}

        .screenshot-tabs {{
            display: flex;
            gap: 5px;
        }}

        .screenshot-tab {{
            padding: 6px 12px;
            border: 1px solid #ddd;
            border-radius: 6px;
            background: white;
            font-size: 12px;
            cursor: pointer;
            transition: all 0.2s;
        }}

        .screenshot-tab.active {{
            background: #667eea;
            color: white;
            border-color: #667eea;
        }}

        .screenshot-player-content {{
            position: relative;
            min-height: 400px;
            background: #f5f5f5;
            display: flex;
            align-items: center;
            justify-content: center;
        }}

        .screenshot-player-img {{
            max-width: 100%;
            max-height: 600px;
            object-fit: contain;
        }}

        .screenshot-player-empty {{
            color: #999;
            font-size: 14px;
        }}

        .screenshot-fullscreen-btn {{
            position: absolute;
            top: 10px;
            right: 10px;
            width: 36px;
            height: 36px;
            border: none;
            border-radius: 8px;
            background: rgba(0,0,0,0.5);
            color: white;
            font-size: 16px;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: background 0.2s;
        }}

        .screenshot-fullscreen-btn:hover {{
            background: rgba(0,0,0,0.7);
        }}

        /* Step highlighting during playback */
        .step.playing {{
            background: #f0f4ff;
            border-left: 4px solid #667eea;
        }}

        .step.playing .step-index {{
            animation: pulse 1s infinite;
        }}

        @keyframes pulse {{
            0%, 100% {{ transform: scale(1); }}
            50% {{ transform: scale(1.1); }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>
                <div class="logo">M</div>
                Midscene Execution Report
            </h1>
            <div class="meta-info">
                <div class="meta-item">
                    <span class="label">Driver:</span>
                    <span>{driver_type}</span>
                </div>
                <div class="meta-item">
                    <span class="label">Started:</span>
                    <span>{start_time}</span>
                </div>
                <div class="meta-item">
                    <span class="label">Duration:</span>
                    <span>{duration}</span>
                </div>
                <div class="meta-item">
                    <span class="label">Status:</span>
                    <span>{status}</span>
                </div>
            </div>
        </div>

        <div class="stats">
            <div class="stat-card">
                <div class="number">{total_steps}</div>
                <div class="label">Total Steps</div>
            </div>
            <div class="stat-card success">
                <div class="number">{success_steps}</div>
                <div class="label">Successful</div>
            </div>
            <div class="stat-card failed">
                <div class="number">{failed_steps}</div>
                <div class="label">Failed</div>
            </div>
        </div>

        <!-- Timeline Visualization -->
        <div class="timeline-visual">
            <div class="timeline-visual-header">
                <div class="timeline-visual-title">Execution Timeline</div>
                <div class="timeline-time-range" id="timeRange"></div>
            </div>
            <div class="timeline-bars" id="timelineBars">
                <div class="timeline-cursor" id="timelineCursor" style="display: none;"></div>
            </div>
        </div>

        <!-- Playback Controls -->
        <div class="playback-controls">
            <div class="playback-main">
                <div class="playback-buttons">
                    <button class="playback-btn" id="prevBtn" title="Previous Step">⏮</button>
                    <button class="playback-btn primary" id="playBtn" title="Play/Pause">▶</button>
                    <button class="playback-btn" id="nextBtn" title="Next Step">⏭</button>
                </div>
                <div class="playback-progress">
                    <div class="playback-progress-bar" id="progressBar">
                        <div class="playback-progress-fill" id="progressFill" style="width: 0%;"></div>
                    </div>
                    <div class="playback-info">
                        <span class="playback-step-info" id="stepInfo">Step 0 / {total_steps}</span>
                        <span id="currentTime">0:00 / 0:00</span>
                    </div>
                </div>
                <div class="playback-speed">
                    <span class="playback-speed-label">Speed:</span>
                    <select class="playback-speed-select" id="speedSelect">
                        <option value="0.5">0.5x</option>
                        <option value="1" selected>1x</option>
                        <option value="2">2x</option>
                        <option value="4">4x</option>
                    </select>
                </div>
            </div>
        </div>

        <!-- Screenshot Player -->
        <div class="screenshot-player">
            <div class="screenshot-player-header">
                <div>
                    <span class="screenshot-player-title">Screenshot Viewer</span>
                    <span class="screenshot-player-step" id="playerStepName"></span>
                </div>
                <div class="screenshot-tabs">
                    <button class="screenshot-tab active" data-type="before">Before</button>
                    <button class="screenshot-tab" data-type="marked">Marked</button>
                    <button class="screenshot-tab" data-type="after">After</button>
                </div>
            </div>
            <div class="screenshot-player-content" id="screenshotContent">
                <span class="screenshot-player-empty">Click Play or select a step to view screenshots</span>
                <button class="screenshot-fullscreen-btn" id="fullscreenBtn" style="display: none;" title="Fullscreen">⛶</button>
            </div>
        </div>

        <div class="timeline">
            <div class="timeline-header">Execution Steps</div>
            {steps_html}
        </div>

        <div class="footer">
            Generated by <a href="https://github.com/anthropics/pymidscene" target="_blank">PyMidscene</a> v{version}
            <br>
            {generation_time}
        </div>
    </div>

    <!-- Image Modal -->
    <div class="modal" id="imageModal">
        <div class="modal-close" onclick="closeModal()">&times;</div>
        <img id="modalImage" src="" alt="Screenshot">
    </div>

    <script>
        // Session data
        const sessionData = {session_json};

        // ========== Playback State ==========
        const playbackState = {{
            isPlaying: false,
            currentStep: -1,
            speed: 1,
            timer: null,
            steps: [],
            totalDuration: 0,
            screenshotType: 'before'
        }};

        // ========== Initialize ==========
        function initPlayback() {{
            // Extract steps from sessionData
            if (sessionData.executions && sessionData.executions[0] && sessionData.executions[0].tasks) {{
                playbackState.steps = sessionData.executions[0].tasks;
            }}

            // Calculate total duration
            playbackState.totalDuration = playbackState.steps.reduce((sum, step) => sum + (step.durationMs || 1000), 0);

            // Build timeline bars
            buildTimelineBars();

            // Update time range display
            updateTimeRange();

            // Setup event listeners
            setupEventListeners();

            // Update initial state
            updatePlaybackUI();
        }}

        // ========== Build Timeline Bars ==========
        function buildTimelineBars() {{
            const container = document.getElementById('timelineBars');
            const cursor = document.getElementById('timelineCursor');

            // Clear existing bars (keep cursor)
            container.innerHTML = '';
            container.appendChild(cursor);

            if (playbackState.steps.length === 0) {{
                container.innerHTML = '<div style="padding: 10px; color: #999; text-align: center; width: 100%;">No steps to display</div>';
                return;
            }}

            playbackState.steps.forEach((step, index) => {{
                const width = (step.durationMs || 1000) / playbackState.totalDuration * 100;
                const bar = document.createElement('div');
                bar.className = `timeline-bar ${{step.status || 'pending'}}`;
                bar.style.width = `${{Math.max(width, 2)}}%`;
                bar.dataset.index = index;

                // Tooltip
                const tooltip = document.createElement('div');
                tooltip.className = 'timeline-tooltip';
                tooltip.textContent = `Step ${{index + 1}}: ${{step.type || 'action'}} (${{step.durationMs || 0}}ms)`;
                bar.appendChild(tooltip);

                // Step number
                if (width > 5) {{
                    bar.textContent = index + 1;
                }}

                // Click handler
                bar.addEventListener('click', () => {{
                    goToStep(index);
                }});

                container.insertBefore(bar, cursor);
            }});
        }}

        // ========== Update Time Range ==========
        function updateTimeRange() {{
            const timeRange = document.getElementById('timeRange');
            const totalSeconds = Math.round(playbackState.totalDuration / 1000);
            const minutes = Math.floor(totalSeconds / 60);
            const seconds = totalSeconds % 60;
            timeRange.textContent = `Total: ${{minutes}}m ${{seconds}}s`;
        }}

        // ========== Setup Event Listeners ==========
        function setupEventListeners() {{
            // Play/Pause button
            document.getElementById('playBtn').addEventListener('click', togglePlay);

            // Previous/Next buttons
            document.getElementById('prevBtn').addEventListener('click', prevStep);
            document.getElementById('nextBtn').addEventListener('click', nextStep);

            // Speed select
            document.getElementById('speedSelect').addEventListener('change', (e) => {{
                playbackState.speed = parseFloat(e.target.value);
                if (playbackState.isPlaying) {{
                    stopTimer();
                    startTimer();
                }}
            }});

            // Progress bar click
            document.getElementById('progressBar').addEventListener('click', (e) => {{
                const rect = e.target.getBoundingClientRect();
                const percent = (e.clientX - rect.left) / rect.width;
                const stepIndex = Math.floor(percent * playbackState.steps.length);
                goToStep(Math.min(stepIndex, playbackState.steps.length - 1));
            }});

            // Screenshot tabs
            document.querySelectorAll('.screenshot-tab').forEach(tab => {{
                tab.addEventListener('click', () => {{
                    document.querySelectorAll('.screenshot-tab').forEach(t => t.classList.remove('active'));
                    tab.classList.add('active');
                    playbackState.screenshotType = tab.dataset.type;
                    updateScreenshotPlayer();
                }});
            }});

            // Fullscreen button
            document.getElementById('fullscreenBtn').addEventListener('click', () => {{
                const img = document.querySelector('.screenshot-player-img');
                if (img) {{
                    openModal(img.src);
                }}
            }});

            // Keyboard shortcuts
            document.addEventListener('keydown', (e) => {{
                if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

                switch(e.key) {{
                    case ' ':
                        e.preventDefault();
                        togglePlay();
                        break;
                    case 'ArrowLeft':
                        e.preventDefault();
                        prevStep();
                        break;
                    case 'ArrowRight':
                        e.preventDefault();
                        nextStep();
                        break;
                }}
            }});
        }}

        // ========== Playback Controls ==========
        function togglePlay() {{
            if (playbackState.isPlaying) {{
                pause();
            }} else {{
                play();
            }}
        }}

        function play() {{
            if (playbackState.steps.length === 0) return;

            playbackState.isPlaying = true;
            document.getElementById('playBtn').textContent = '⏸';

            // Start from beginning if at end
            if (playbackState.currentStep >= playbackState.steps.length - 1) {{
                playbackState.currentStep = -1;
            }}

            // Go to first step if not started
            if (playbackState.currentStep < 0) {{
                goToStep(0);
            }}

            startTimer();
        }}

        function pause() {{
            playbackState.isPlaying = false;
            document.getElementById('playBtn').textContent = '▶';
            stopTimer();
        }}

        function startTimer() {{
            stopTimer();
            const step = playbackState.steps[playbackState.currentStep];
            const duration = (step?.durationMs || 1000) / playbackState.speed;

            playbackState.timer = setTimeout(() => {{
                if (playbackState.currentStep < playbackState.steps.length - 1) {{
                    nextStep();
                    if (playbackState.isPlaying) {{
                        startTimer();
                    }}
                }} else {{
                    pause();
                }}
            }}, Math.max(duration, 200));
        }}

        function stopTimer() {{
            if (playbackState.timer) {{
                clearTimeout(playbackState.timer);
                playbackState.timer = null;
            }}
        }}

        function prevStep() {{
            if (playbackState.currentStep > 0) {{
                goToStep(playbackState.currentStep - 1);
            }}
        }}

        function nextStep() {{
            if (playbackState.currentStep < playbackState.steps.length - 1) {{
                goToStep(playbackState.currentStep + 1);
            }}
        }}

        function goToStep(index) {{
            if (index < 0 || index >= playbackState.steps.length) return;

            playbackState.currentStep = index;
            updatePlaybackUI();
            updateTimelineHighlight();
            updateScreenshotPlayer();
            updateStepHighlight();
            scrollToStep(index);
        }}

        // ========== UI Updates ==========
        function updatePlaybackUI() {{
            const stepInfo = document.getElementById('stepInfo');
            const progressFill = document.getElementById('progressFill');
            const currentTime = document.getElementById('currentTime');
            const prevBtn = document.getElementById('prevBtn');
            const nextBtn = document.getElementById('nextBtn');

            const current = playbackState.currentStep + 1;
            const total = playbackState.steps.length;

            stepInfo.textContent = `Step ${{current}} / ${{total}}`;

            const progress = total > 0 ? (current / total * 100) : 0;
            progressFill.style.width = `${{progress}}%`;

            // Calculate time
            let elapsed = 0;
            for (let i = 0; i <= playbackState.currentStep && i < playbackState.steps.length; i++) {{
                elapsed += playbackState.steps[i]?.durationMs || 0;
            }}
            const elapsedSec = Math.round(elapsed / 1000);
            const totalSec = Math.round(playbackState.totalDuration / 1000);
            currentTime.textContent = `${{formatTime(elapsedSec)}} / ${{formatTime(totalSec)}}`;

            // Button states
            prevBtn.disabled = playbackState.currentStep <= 0;
            nextBtn.disabled = playbackState.currentStep >= playbackState.steps.length - 1;
        }}

        function formatTime(seconds) {{
            const mins = Math.floor(seconds / 60);
            const secs = seconds % 60;
            return `${{mins}}:${{secs.toString().padStart(2, '0')}}`;
        }}

        function updateTimelineHighlight() {{
            // Remove active class from all bars
            document.querySelectorAll('.timeline-bar').forEach(bar => {{
                bar.classList.remove('active');
            }});

            // Add active class to current bar
            const currentBar = document.querySelector(`.timeline-bar[data-index="${{playbackState.currentStep}}"]`);
            if (currentBar) {{
                currentBar.classList.add('active');
            }}

            // Update cursor position
            const cursor = document.getElementById('timelineCursor');
            if (playbackState.currentStep >= 0) {{
                let leftPercent = 0;
                for (let i = 0; i < playbackState.currentStep; i++) {{
                    leftPercent += (playbackState.steps[i]?.durationMs || 1000) / playbackState.totalDuration * 100;
                }}
                // Add half of current step
                leftPercent += (playbackState.steps[playbackState.currentStep]?.durationMs || 1000) / playbackState.totalDuration * 50;
                cursor.style.left = `${{leftPercent}}%`;
                cursor.style.display = 'block';
            }} else {{
                cursor.style.display = 'none';
            }}
        }}

        function updateScreenshotPlayer() {{
            const content = document.getElementById('screenshotContent');
            const stepName = document.getElementById('playerStepName');
            const fullscreenBtn = document.getElementById('fullscreenBtn');

            if (playbackState.currentStep < 0 || playbackState.currentStep >= playbackState.steps.length) {{
                content.innerHTML = '<span class="screenshot-player-empty">Click Play or select a step to view screenshots</span>';
                fullscreenBtn.style.display = 'none';
                stepName.textContent = '';
                return;
            }}

            const step = playbackState.steps[playbackState.currentStep];
            stepName.textContent = ` - Step ${{playbackState.currentStep + 1}}: ${{step.type || 'action'}}`;

            // Get screenshot based on type
            let screenshot = null;
            switch(playbackState.screenshotType) {{
                case 'before':
                    screenshot = step.screenshotBefore;
                    break;
                case 'marked':
                    screenshot = step.screenshotMarked || step.screenshotBefore;
                    break;
                case 'after':
                    screenshot = step.screenshotAfter || step.screenshotMarked || step.screenshotBefore;
                    break;
            }}

            if (screenshot) {{
                content.innerHTML = `<img class="screenshot-player-img" src="data:image/png;base64,${{screenshot}}" alt="Screenshot">`;
                content.appendChild(fullscreenBtn);
                fullscreenBtn.style.display = 'flex';
            }} else {{
                content.innerHTML = '<span class="screenshot-player-empty">No screenshot available for this step</span>';
                fullscreenBtn.style.display = 'none';
            }}
        }}

        function updateStepHighlight() {{
            // Remove playing class from all steps
            document.querySelectorAll('.step').forEach(step => {{
                step.classList.remove('playing');
            }});

            // Add playing class to current step
            const steps = document.querySelectorAll('.step');
            if (playbackState.currentStep >= 0 && playbackState.currentStep < steps.length) {{
                steps[playbackState.currentStep].classList.add('playing');
            }}
        }}

        function scrollToStep(index) {{
            const steps = document.querySelectorAll('.step');
            if (index >= 0 && index < steps.length) {{
                steps[index].scrollIntoView({{ behavior: 'smooth', block: 'center' }});
            }}
        }}

        // ========== Step Expansion ==========
        document.querySelectorAll('.step-header').forEach((header, index) => {{
            header.addEventListener('click', () => {{
                header.parentElement.classList.toggle('expanded');
                // Also update playback to this step
                goToStep(index);
            }});
        }});

        // ========== Image Modal ==========
        function openModal(imgSrc) {{
            const modal = document.getElementById('imageModal');
            const modalImg = document.getElementById('modalImage');
            modalImg.src = imgSrc;
            modal.classList.add('active');
        }}

        function closeModal() {{
            document.getElementById('imageModal').classList.remove('active');
        }}

        document.getElementById('imageModal').addEventListener('click', (e) => {{
            if (e.target.id === 'imageModal') {{
                closeModal();
            }}
        }});

        document.addEventListener('keydown', (e) => {{
            if (e.key === 'Escape') {{
                closeModal();
            }}
        }});

        // Make screenshots clickable
        document.querySelectorAll('.screenshot-img').forEach(img => {{
            img.addEventListener('click', () => {{
                openModal(img.src);
            }});
        }});

        // ========== Initialize on DOM Ready ==========
        document.addEventListener('DOMContentLoaded', initPlayback);
        // Also try to init immediately if DOM is already ready
        if (document.readyState !== 'loading') {{
            initPlayback();
        }}
    </script>
</body>
</html>'''

    def _generate_step_html(self, step: ReportStep) -> str:
        """生成单个步骤的 HTML"""
        status_class = step.status

        # 截图 HTML
        screenshots_html = ""
        if step.screenshot_before or step.screenshot_after or step.screenshot_marked:
            screenshots_html = '<div class="screenshots">'

            if step.screenshot_before:
                screenshots_html += f'''
                <div class="screenshot-panel">
                    <div class="screenshot-label">Before</div>
                    <img class="screenshot-img" src="data:image/png;base64,{step.screenshot_before}" alt="Before">
                </div>'''

            # 优先显示带标记的截图
            if step.screenshot_marked:
                screenshots_html += f'''
                <div class="screenshot-panel">
                    <div class="screenshot-label">Marked</div>
                    <img class="screenshot-img" src="data:image/png;base64,{step.screenshot_marked}" alt="Marked">
                </div>'''
            elif step.screenshot_after:
                screenshots_html += f'''
                <div class="screenshot-panel">
                    <div class="screenshot-label">After</div>
                    <img class="screenshot-img" src="data:image/png;base64,{step.screenshot_after}" alt="After">
                </div>'''

            screenshots_html += '</div>'

        # 元素信息 HTML
        element_html = ""
        if step.element_bbox or step.element_center:
            element_html = '''
            <div class="detail-card">
                <h4>Element Location</h4>
                <div class="element-info">'''

            if step.element_bbox:
                element_html += f'''
                    <div class="row">
                        <span class="label">Bounding Box</span>
                        <span class="value">[{step.element_bbox[0]}, {step.element_bbox[1]}, {step.element_bbox[2]}, {step.element_bbox[3]}]</span>
                    </div>'''

            if step.element_center:
                element_html += f'''
                    <div class="row">
                        <span class="label">Click Point</span>
                        <span class="value">({step.element_center[0]}, {step.element_center[1]})</span>
                    </div>'''

            if step.element_description:
                element_html += f'''
                    <div class="row">
                        <span class="label">Description</span>
                        <span class="value">{step.element_description}</span>
                    </div>'''

            element_html += '''
                </div>
            </div>'''

        # AI 信息 HTML
        ai_html = ""
        if step.ai_model or step.ai_tokens or step.ai_response:
            ai_html = '''
            <div class="detail-card">
                <h4>AI Information</h4>
                <div class="element-info">'''

            if step.ai_model:
                ai_html += f'''
                    <div class="row">
                        <span class="label">Model</span>
                        <span class="value">{step.ai_model}</span>
                    </div>'''

            if step.ai_tokens:
                ai_html += f'''
                    <div class="row">
                        <span class="label">Tokens Used</span>
                        <span class="value">{step.ai_tokens}</span>
                    </div>'''

            ai_html += '</div>'

            if step.ai_response:
                # 截断过长的响应
                response = step.ai_response
                if len(response) > 500:
                    response = response[:500] + "..."
                ai_html += f'<pre>{response}</pre>'

            ai_html += '</div>'

        # 错误信息 HTML
        error_html = ""
        if step.error_message:
            error_html = f'<div class="error-message">{step.error_message}</div>'

        return f'''
        <div class="step {status_class}">
            <div class="step-header">
                <div class="step-index">{step.step_index}</div>
                <div class="step-info">
                    <div class="step-action">
                        <span class="action-badge {step.action_type}">{step.action_type}</span>
                        {step.prompt[:80] + "..." if len(step.prompt) > 80 else step.prompt}
                    </div>
                    <div class="step-prompt">{step.prompt}</div>
                </div>
                <div class="step-meta">
                    <span>{step.duration_ms}ms</span>
                    <span>{step.timestamp}</span>
                </div>
                <div class="step-toggle">▼</div>
            </div>
            <div class="step-details">
                {screenshots_html}
                <div class="details-grid">
                    {element_html}
                    {ai_html}
                </div>
                {error_html}
            </div>
        </div>'''

    def generate(self, session: ReportSession) -> str:
        """
        生成完整的 HTML 报告

        Args:
            session: 报告会话数据

        Returns:
            HTML 字符串
        """
        # 计算持续时间
        duration = "N/A"
        if session.start_time and session.end_time:
            try:
                start = datetime.fromisoformat(session.start_time)
                end = datetime.fromisoformat(session.end_time)
                delta = end - start
                total_seconds = int(delta.total_seconds())
                if total_seconds < 60:
                    duration = f"{total_seconds}s"
                else:
                    minutes = total_seconds // 60
                    seconds = total_seconds % 60
                    duration = f"{minutes}m {seconds}s"
            except:
                pass

        # 生成步骤 HTML
        steps_html = ""
        for step in session.steps:
            steps_html += self._generate_step_html(step)

        if not steps_html:
            steps_html = '<div style="padding: 40px; text-align: center; color: #999;">No steps recorded</div>'

        # 填充模板
        html = self._get_html_template().format(
            session_id=session.session_id,
            driver_type=session.driver_type,
            start_time=session.start_time,
            duration=duration,
            status=session.status.upper(),
            total_steps=session.total_steps,
            success_steps=session.success_steps,
            failed_steps=session.failed_steps,
            steps_html=steps_html,
            version=self.VERSION,
            generation_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            session_json=json.dumps(session.to_dict(), ensure_ascii=False)
        )

        return html

    def save(
        self,
        session: ReportSession,
        report_dir: str,
        filename: Optional[str] = None
    ) -> str:
        """
        保存报告到文件

        Args:
            session: 报告会话数据
            report_dir: 报告目录
            filename: 文件名（可选）

        Returns:
            保存的文件路径
        """
        # 生成文件名
        if filename is None:
            timestamp = datetime.now()
            session_id_short = session.session_id[:8]
            filename = f"{session.driver_type}-{timestamp.strftime('%Y-%m-%d_%H-%M-%S')}-{session_id_short}.html"

        # 确保目录存在
        report_path = Path(report_dir)
        report_path.mkdir(parents=True, exist_ok=True)

        # 生成并保存 HTML
        html_content = self.generate(session)
        file_path = report_path / filename

        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(html_content)

        logger.info(f"Report saved to: {file_path}")
        return str(file_path)


# 默认实例
_default_generator: Optional[HTMLReportGenerator] = None


def get_default_report_generator() -> HTMLReportGenerator:
    """获取默认的报告生成器实例"""
    global _default_generator
    if _default_generator is None:
        _default_generator = HTMLReportGenerator()
    return _default_generator


__all__ = [
    "HTMLReportGenerator",
    "ReportSession",
    "ReportStep",
    "get_default_report_generator",
]
