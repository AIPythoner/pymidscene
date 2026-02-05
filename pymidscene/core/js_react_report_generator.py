# -*- coding: utf-8 -*-
"""
JS React 报告生成器 - 使用 JS 版本的 React 前端模板

此模块生成与 JS 版本 Midscene 100% 视觉一致的 HTML 报告:
1. 使用从 JS 版本提取的完整 React 前端模板（包含 React + Ant Design 组件）
2. Python 只负责生成 GroupedActionDump 数据
3. 通过 <script type="midscene_web_dump"> 标签注入数据，与 JS 版本完全一致

这样生成的报告具有:
- 左侧步骤树（WaitTo, Assert, Action, Plan, Locate 等）
- 顶部胶卷时间轴（Filmstrip）
- 中间交互式大屏截图
- 完整的播放功能
"""

import json
import uuid
import time
import re
import os
from datetime import datetime
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field
from pathlib import Path

from ..shared.logger import logger


def _escape_script_tag(content: str) -> str:
    """转义 script 标签内容，防止 HTML 解析错误"""
    return content.replace('</script>', '<\\/script>')


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
        result = {
            "id": self.id,
            "reason": self.reason,
            "text": self.text,
        }
        if self.indexId is not None:
            result["indexId"] = self.indexId
        if self.rect:
            result["rect"] = self.rect
        if self.center:
            result["center"] = self.center
        return result


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
    - type: 任务类型 (Locate, Planning, Insight, Action Space)
    - subType: 子类型 (Locate, Plan, Tap, Input, etc.)
    - status: 状态 (pending, running, finished, failed)
    - param: 任务参数
    - output: 输出结果
    - recorder: 截图记录数组
    - timing: 时间信息
    - usage: AI token 使用
    - uiContext: UI 上下文（包含截图尺寸，动画播放需要）
    """
    type: str  # "Planning" | "Insight" | "Action Space"
    subType: Optional[str] = None  # "Locate" | "Plan" | "Tap" | "Input" | etc.
    subTask: bool = False
    status: str = "finished"  # "pending" | "running" | "finished" | "failed"
    
    # 参数 - 根据类型不同结构不同
    param: Optional[Dict[str, Any]] = None
    thought: Optional[str] = None
    
    # 输出
    output: Optional[Any] = None
    log: Optional[Dict[str, Any]] = None
    
    # 截图记录 - 与 JS 版本格式一致
    recorder: List[Dict] = field(default_factory=list)
    
    # UI 上下文 - 动画播放需要 size 信息
    uiContext: Optional[Dict[str, Any]] = None
    
    # 时间和资源
    timing: Optional[TaskTiming] = None
    usage: Optional[AIUsage] = None
    
    # 定位结果
    matchedElement: Optional[List[MatchedElement]] = None
    
    # 错误信息
    error: Optional[str] = None
    errorStack: Optional[str] = None
    errorMessage: Optional[str] = None

    def to_dict(self) -> dict:
        result: Dict[str, Any] = {
            "type": self.type,
            "status": self.status,
        }
        
        if self.subType:
            result["subType"] = self.subType
        if self.subTask:
            result["subTask"] = self.subTask
        if self.param:
            result["param"] = self.param
        if self.thought:
            result["thought"] = self.thought
        if self.output is not None:
            result["output"] = self.output
        if self.log:
            result["log"] = self.log
        if self.recorder:
            result["recorder"] = self.recorder
        if self.uiContext:
            result["uiContext"] = self.uiContext
        if self.timing:
            result["timing"] = self.timing.to_dict()
        if self.usage:
            result["usage"] = self.usage.to_dict()
        if self.matchedElement:
            result["matchedElement"] = [e.to_dict() for e in self.matchedElement]
        if self.error:
            result["error"] = self.error
        if self.errorStack:
            result["errorStack"] = self.errorStack
        if self.errorMessage:
            result["errorMessage"] = self.errorMessage
            
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
            # 注意：JS 版本顶层没有 logTime
            "groupName": self.groupName,
            "groupDescription": self.groupDescription,
            "executions": [e.to_dict() for e in self.executions],
            "modelBriefs": self.modelBriefs,
        }


class JSReactReportGenerator:
    """
    JS React 报告生成器
    
    使用从 JS 版本提取的完整 React 前端模板生成报告。
    Python 只负责生成 GroupedActionDump 数据，通过 <script type="midscene_web_dump"> 注入。
    """
    
    VERSION = "1.0.0"
    
    # JS 版本模板的缓存
    _js_template_cache: Optional[str] = None
    
    # 可能的 JS 模板源路径
    JS_TEMPLATE_SOURCES = [
        r"E:\code\qinghu\js-rpa-script\node_modules\@midscene\core\dist\lib\utils.js",
    ]
    
    def __init__(self):
        """初始化报告生成器"""
        self._current_dump: Optional[GroupedActionDump] = None
        self._current_execution: Optional[ExecutionDump] = None
        self._js_template: Optional[str] = None
        
    def _load_js_template(self) -> Optional[str]:
        """
        从 JS 版本加载 React HTML 模板
        
        模板包含完整的 React + Ant Design 组件代码
        """
        if self._js_template is not None:
            return self._js_template
            
        if JSReactReportGenerator._js_template_cache is not None:
            self._js_template = JSReactReportGenerator._js_template_cache
            return self._js_template
        
        # 尝试从已有的 JS 报告文件中提取模板
        js_report_patterns = [
            r"E:\code\qinghu\js-rpa-script\agents\ai-demo\midscene_run\report\*.html",
            r"E:\code\qinghu\js-rpa-script\*\midscene_run\report\*.html",
        ]
        
        import glob
        for pattern in js_report_patterns:
            files = glob.glob(pattern)
            if files:
                # 使用最新的报告文件
                latest_file = max(files, key=os.path.getmtime)
                try:
                    with open(latest_file, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    # 找到真正的数据注入位置
                    # JS 报告结构: ...JS代码...</script></body>\n</html>\n<script type="midscene_web_dump">
                    # 注意：JS代码中可能包含 "</html>" 字符串，需要找到真正的 HTML 结束标签
                    
                    # 方法1: 查找 </script></body> 后面紧跟的 </html>（真正的 HTML 结束）
                    # 真正的结构是: ...</script></body>\n</html>\n<script type="midscene_web_dump">
                    real_end_match = re.search(r'</script>\s*</body>\s*\n</html>\s*\n', content)
                    if real_end_match:
                        # 模板截取到 </html> 结束（包含换行）
                        template_end = real_end_match.end()
                        template = content[:template_end].rstrip() + '\n'
                        # 确保模板以 </html> 结尾
                        if '</html>' in template[-20:]:
                            JSReactReportGenerator._js_template_cache = template
                            self._js_template = template
                            logger.info(f"Loaded JS React template from: {latest_file}")
                            return template
                    
                    # 方法2: 查找带换行符的数据脚本标签，往前截取
                    data_match = re.search(r'\n</html>\s*\n<script type="midscene_web_dump"', content)
                    if data_match:
                        # 找到 </html> 的结束位置
                        template_end = content.find('</html>', data_match.start()) + len('</html>')
                        template = content[:template_end]
                        JSReactReportGenerator._js_template_cache = template
                        self._js_template = template
                        logger.info(f"Loaded JS React template from: {latest_file}")
                        return template
                    
                    # 方法3: 使用 rfind 找最后一个 </html>
                    last_html_end = content.rfind('</html>')
                    if last_html_end > 0:
                        template = content[:last_html_end + len('</html>')]
                        JSReactReportGenerator._js_template_cache = template
                        self._js_template = template
                        logger.info(f"Loaded JS React template from: {latest_file} (using rfind)")
                        return template
                        
                except Exception as e:
                    logger.warning(f"Failed to load template from {latest_file}: {e}")
        
        # 尝试从 utils.js 中提取模板
        for source_path in self.JS_TEMPLATE_SOURCES:
            if os.path.exists(source_path):
                try:
                    with open(source_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    # 提取 getReportTpl() 函数中的模板
                    match = re.search(
                        r'/\*REPORT_HTML_REPLACED\*/\s*"(.*?)";\s*return\s+reportTpl',
                        content,
                        re.DOTALL
                    )
                    if match:
                        template = match.group(1)
                        # 解码转义字符
                        template = template.encode('utf-8').decode('unicode_escape')
                        JSReactReportGenerator._js_template_cache = template
                        self._js_template = template
                        logger.info(f"Loaded JS React template from: {source_path}")
                        return template
                except Exception as e:
                    logger.warning(f"Failed to load template from {source_path}: {e}")
        
        logger.warning("Could not load JS React template, using fallback")
        return None
    
    def _get_fallback_template(self) -> str:
        """获取回退模板（当无法加载 JS 模板时使用）"""
        return '''<!doctype html>
<html>
  <head>
    <title>Report - PyMidscene</title>
    <link rel="icon" type="image/png" sizes="32x32" 
          href="https://lf3-static.bytednsdoc.com/obj/eden-cn/vhaeh7vhabf/favicon-32x32.png" />
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
      body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; 
             background: #f5f7fa; margin: 0; padding: 20px; }
      .notice { max-width: 800px; margin: 100px auto; padding: 40px; background: white; 
                border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.1); text-align: center; }
      .notice h1 { color: #667eea; margin-bottom: 20px; }
      .notice p { color: #666; line-height: 1.8; }
      .notice code { background: #f0f0f0; padding: 2px 6px; border-radius: 4px; }
    </style>
  </head>
  <body>
    <div class="notice">
      <h1>PyMidscene Report</h1>
      <p>无法加载 JS 版本的 React 可视化模板。</p>
      <p>要获得完整的交互式报告体验（包含时间轴、播放功能），请确保：</p>
      <p>1. 已安装 JS 版本的 <code>@midscene/core</code> 包</p>
      <p>2. 或者存在已生成的 JS 版本报告文件</p>
      <p style="margin-top: 30px; color: #999;">报告数据已嵌入下方，可被 JS 版本解析。</p>
    </div>
'''
    
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
        sub_type: Optional[str] = None,
        prompt: Optional[str] = None,
        status: str = "finished",
        screenshot_before: Optional[str] = None,
        screenshot_after: Optional[str] = None,
        element_rect: Optional[Dict[str, int]] = None,
        element_center: Optional[List[int]] = None,
        element_text: Optional[str] = None,
        duration_ms: int = 0,
        ai_tokens: Optional[int] = None,
        ai_prompt_tokens: Optional[int] = None,
        ai_completion_tokens: Optional[int] = None,
        error: Optional[str] = None,
        thought: Optional[str] = None,
        output: Optional[Any] = None,
        screenshot_width: Optional[int] = None,
        screenshot_height: Optional[int] = None,
    ):
        """
        添加执行任务
        
        Args:
            task_type: 任务类型 (Planning, Insight, Action Space)
            sub_type: 子类型 (Locate, Plan, Tap, Input, etc.)
            prompt: 用户指令
            status: 状态 (finished, failed, pending)
            screenshot_before: 操作前截图 (base64)
            screenshot_after: 操作后截图 (base64)
            element_rect: 元素边界框 {left, top, width, height}
            element_center: 元素中心点 [x, y]
            element_text: 元素文本
            duration_ms: 耗时毫秒
            ai_tokens: AI token 总数
            ai_prompt_tokens: 提示 token 数
            ai_completion_tokens: 完成 token 数
            error: 错误信息
            thought: AI 思考过程
            output: 输出结果
            screenshot_width: 截图宽度（播放动画需要）
            screenshot_height: 截图高度（播放动画需要）
        """
        if not self._current_execution:
            self.start_session()
        
        # 构建截图记录 - 与 JS 版本格式一致
        recorder = []
        ts = int(time.time() * 1000)
        
        # 确保截图有正确的 data:image 前缀
        def ensure_data_url(screenshot: str) -> str:
            if not screenshot:
                return screenshot
            if screenshot.startswith('data:image'):
                return screenshot
            # 添加 PNG 格式前缀（如果没有的话）
            return f"data:image/png;base64,{screenshot}"
        
        # JS 版本的 screenshot 是一个对象 {"base64": "data:image/..."}
        def make_screenshot_obj(screenshot: str) -> dict:
            return {"base64": ensure_data_url(screenshot)}
        
        if screenshot_before:
            recorder.append({
                "type": "screenshot",
                "ts": ts,
                "screenshot": make_screenshot_obj(screenshot_before),
                "timing": "after-calling",  # JS 版本使用 after-calling
            })
        if screenshot_after:
            recorder.append({
                "type": "screenshot", 
                "ts": ts + duration_ms,
                "screenshot": make_screenshot_obj(screenshot_after),
                "timing": "after-calling",  # JS 版本使用 after-calling
            })
        
        # 构建匹配元素
        matched_element = None
        if element_rect or element_center:
            matched_element = [MatchedElement(
                id=str(uuid.uuid4())[:8],
                reason=prompt or "",
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
            start=ts - duration_ms,
            end=ts,
            cost=duration_ms,
        )
        
        # 构建参数
        param = {}
        if prompt:
            param["prompt"] = prompt
        # 如果是 Locate 任务且有元素信息，添加 bbox 到 param
        if sub_type == "Locate" and element_rect:
            param["bbox"] = [
                element_rect.get("left", 0),
                element_rect.get("top", 0),
                element_rect.get("left", 0) + element_rect.get("width", 0),
                element_rect.get("top", 0) + element_rect.get("height", 0),
            ]
        
        # 构建 output - Locate 任务需要 output.element 来实现动画效果
        task_output = output
        if sub_type == "Locate" and (element_rect or element_center):
            task_output = {
                "element": {
                    "rect": element_rect or {"left": 0, "top": 0, "width": 0, "height": 0},
                    "center": element_center or [0, 0],
                    "description": element_text or prompt or "",
                }
            }
        
        # 构建 uiContext - 动画播放需要 size 信息
        # 如果没有提供尺寸，尝试从截图中解析
        ui_context = None
        width = screenshot_width
        height = screenshot_height
        
        # 获取截图数据用于 uiContext
        screenshot_data = screenshot_before or screenshot_after
        screenshot_for_context = None
        
        if not width or not height:
            # 尝试从 base64 截图中获取尺寸
            if screenshot_data:
                try:
                    import base64
                    from io import BytesIO
                    # 移除 data:image 前缀
                    raw_data = screenshot_data
                    if raw_data.startswith('data:image'):
                        raw_data = raw_data.split(',', 1)[1]
                    img_data = base64.b64decode(raw_data)
                    # 尝试用 PIL 获取尺寸
                    try:
                        from PIL import Image
                        img = Image.open(BytesIO(img_data))
                        width, height = img.size
                    except ImportError:
                        # 如果没有 PIL，尝试从 PNG 头部解析
                        if img_data[:8] == b'\x89PNG\r\n\x1a\n':
                            width = int.from_bytes(img_data[16:20], 'big')
                            height = int.from_bytes(img_data[20:24], 'big')
                except Exception:
                    pass
        
        # 默认尺寸
        if not width:
            width = 1920
        if not height:
            height = 1080
        
        # 构建 uiContext.screenshot（与 JS 版本一致）
        if screenshot_data:
            screenshot_for_context = {"base64": ensure_data_url(screenshot_data)}
            
        ui_context = {
            "size": {
                "width": width,
                "height": height,
                "dpr": 1,  # 默认 dpr 为 1
            },
            "screenshot": screenshot_for_context,
        }
        
        task = ExecutionTask(
            type=task_type,
            subType=sub_type,
            status=status,
            param=param if param else None,
            thought=thought if thought else prompt,  # 如果没有 thought，使用 prompt 作为描述
            output=task_output,  # 使用构建的 output（Locate 任务包含 element 信息）
            recorder=recorder,
            uiContext=ui_context,
            matchedElement=matched_element,
            timing=timing,
            usage=usage,
            error=error if error else None,  # 只在有错误时设置
            errorMessage=error if error else None,  # 只在有错误时设置
        )
        
        if self._current_dump is None:
            self.start_session()
        assert self._current_dump is not None
        
        # JS 版本每个操作是独立的 execution，这样整体播放功能才能正常工作
        # 为每个 task 创建独立的 execution
        execution_name = f"{sub_type or task_type} - {prompt or 'task'}"
        new_execution = ExecutionDump(
            name=execution_name,
            description=None,
            tasks=[task],
            logTime=ts,
        )
        self._current_dump.executions.append(new_execution)
    
    def generate_data_script(self) -> str:
        """
        生成数据注入的 script 标签
        
        格式与 JS 版本完全一致:
        <script type="midscene_web_dump" type="application/json">
        {JSON数据}
        </script>
        """
        if not self._current_dump:
            self.start_session()
        
        assert self._current_dump is not None
        data_json = json.dumps(
            self._current_dump.to_dict(),
            ensure_ascii=False,
            separators=(',', ':')
        )
        
        escaped_json = _escape_script_tag(data_json)
        
        return f'<script type="midscene_web_dump" type="application/json">\n{escaped_json}\n</script>'
    
    def generate_html(self) -> str:
        """
        生成完整的 HTML 报告
        
        使用 JS 版本的 React 模板 + Python 生成的数据
        
        Returns:
            完整的 HTML 字符串
        """
        # 加载 JS 模板
        template = self._load_js_template()
        
        if template:
            # 使用 JS 版本的 React 模板
            # 模板已经包含完整的 HTML 结构（到 </html> 为止）
            html = template
        else:
            # 使用回退模板
            html = self._get_fallback_template()
        
        # 注入数据
        data_script = self.generate_data_script()
        
        # 在模板后添加数据脚本
        # 注意：模板已经包含 </html>，数据脚本放在其后
        html += "\n" + data_script
        
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
_default_generator: Optional[JSReactReportGenerator] = None


def get_js_react_report_generator() -> JSReactReportGenerator:
    """获取默认的 JS React 报告生成器"""
    global _default_generator
    if _default_generator is None:
        _default_generator = JSReactReportGenerator()
    return _default_generator


__all__ = [
    "JSReactReportGenerator",
    "GroupedActionDump",
    "ExecutionDump",
    "ExecutionTask",
    "MatchedElement",
    "AIUsage",
    "TaskTiming",
    "get_js_react_report_generator",
]
