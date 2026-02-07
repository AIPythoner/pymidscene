"""
Agent 核心类 - 对应 packages/core/src/agent/agent.ts

这是 PyMidscene 的核心入口，提供 AI 驱动的自动化能力。
"""

from typing import Optional, Dict, Any, List, Union, Tuple
import time
import asyncio

from ..ai_model import call_ai
from ..ai_model.prompts import (
    system_prompt_to_locate_element,
    find_element_prompt,
    system_prompt_to_extract,
    extract_data_prompt,
    parse_xml_extraction_response,
)
from ..agent.task_cache import TaskCache, PlanningCache, LocateCache
from ..dump import ExecutionRecorder, SessionRecorder, create_session_recorder
from ..types import ScreenshotItem
from ...web_integration.base import AbstractInterface
from ...shared.types import Size, Rect, LocateResultElement
from ...shared.logger import logger
from ...shared.utils import calculate_center, format_bbox, adapt_bbox
from ...shared.env import (
    ModelConfigManager,
    ModelConfig,
    get_global_model_config_manager,
    INTENT_DEFAULT,
)


class Agent:
    """
    AI 驱动的自动化 Agent

    整合了 AI 模型、缓存系统和浏览器控制，提供高级的自动化能力。

    使用方式：
    1. 通过环境变量配置模型（推荐）：
        os.environ["MIDSCENE_MODEL_NAME"] = "qwen-vl-max"
        os.environ["OPENAI_API_KEY"] = "your-key"
        os.environ["OPENAI_BASE_URL"] = "https://dashscope.aliyuncs.com/compatible-mode/v1"
        os.environ["MIDSCENE_MODEL_FAMILY"] = "qwen2.5-vl"

        agent = Agent(interface)

    2. 通过 model_config 字典配置：
        agent = Agent(interface, model_config={
            "MIDSCENE_MODEL_NAME": "qwen-vl-max",
            "OPENAI_API_KEY": "your-key",
            "OPENAI_BASE_URL": "https://...",
            "MIDSCENE_MODEL_FAMILY": "qwen2.5-vl",
        })
    """

    def __init__(
        self,
        interface: AbstractInterface,
        model_config: Optional[Dict[str, Any]] = None,
        cache_id: Optional[str] = None,
        cache_strategy: str = "read-write",
        cache_dir: Optional[str] = None,
        enable_recording: bool = True,  # 默认启用记录
        driver_type: str = "playwright",
        report_dir: Optional[str] = None,
    ):
        """
        初始化 Agent

        Args:
            interface: 设备接口（WebPage 等）
            model_config: 模型配置字典，键为环境变量名称
                - MIDSCENE_MODEL_NAME: 模型名称
                - OPENAI_API_KEY / MIDSCENE_MODEL_API_KEY: API 密钥
                - OPENAI_BASE_URL / MIDSCENE_MODEL_BASE_URL: API 基础 URL
                - MIDSCENE_MODEL_FAMILY: 模型家族（qwen2.5-vl, doubao-vision 等）
            cache_id: 缓存 ID
            cache_strategy: 缓存策略（read-only, read-write, write-only）
            cache_dir: 缓存目录
            enable_recording: 是否启用执行记录（默认启用）
            driver_type: 驱动类型（playwright, selenium 等）
            report_dir: 报告保存目录（默认为当前目录）
        """
        self.interface = interface
        self.driver_type = driver_type

        # 初始化模型配置管理器
        if model_config:
            # 使用传入的配置（隔离模式）
            self.model_config_manager = ModelConfigManager(model_config)
        else:
            # 使用全局配置管理器（从环境变量读取）
            self.model_config_manager = get_global_model_config_manager()

        # 初始化缓存
        self.task_cache: Optional[TaskCache] = None
        if cache_id:
            self.task_cache = TaskCache(
                cache_id=cache_id,
                is_cache_result_used=(cache_strategy != "write-only"),
                cache_dir=cache_dir,
                strategy=cache_strategy
            )
            logger.info(f"Task cache initialized: {cache_id}")

        # 初始化会话记录器（新的日志系统）
        self.enable_recording = enable_recording
        self.session_recorder: Optional[SessionRecorder] = None
        self.recorder: Optional[ExecutionRecorder] = None  # 保持向后兼容

        if enable_recording:
            self.session_recorder = create_session_recorder(
                driver_type=driver_type,
                base_dir=report_dir,
                auto_save=True
            )
            # 同时保留旧的 recorder 以兼容
            self.recorder = ExecutionRecorder(
                name="Agent Execution",
                description="Automated execution"
            )
            logger.info(f"Session recording enabled: {self.session_recorder.session_id}")

        logger.info(
            f"Agent initialized: "
            f"cache={'enabled' if cache_id else 'disabled'}, "
            f"recording={'enabled' if enable_recording else 'disabled'}"
        )

    def _get_model_config(self, intent: str = INTENT_DEFAULT) -> ModelConfig:
        """获取模型配置"""
        return self.model_config_manager.get_model_config(intent)

    def _build_messages(
        self,
        system_prompt: str,
        user_prompt: str,
        screenshot_b64: str
    ) -> List[Dict[str, Any]]:
        """构建 AI 消息"""
        return [
            {
                "role": "system",
                "content": system_prompt
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{screenshot_b64}"
                        }
                    },
                    {
                        "type": "text",
                        "text": user_prompt
                    }
                ]
            }
        ]

    def _call_ai_with_config(
        self,
        messages: List[Dict[str, Any]],
        intent: str = INTENT_DEFAULT
    ) -> Dict[str, Any]:
        """
        使用配置调用 AI
        
        支持两种调用方式：
        1. httpx 直接请求（适用于反代、Gemini 等）- 更兼容
        2. OpenAI SDK（适用于标准 OpenAI 兼容 API）- 备用
        """
        config = self._get_model_config(intent)

        # 统一使用 httpx 直接请求，更兼容各种反代和 API 格式
        return self._call_with_httpx(config, messages)

    def _call_with_httpx(
        self,
        config: ModelConfig,
        messages: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        使用 httpx 直接请求（参考 GeminiHttpClient 实现）
        
        兼容：
        - Gemini 反代（OpenAI 兼容格式）
        - 豆包/千问等 OpenAI 兼容 API
        - 任何 OpenAI 格式的反代服务
        """
        import httpx

        # 构造请求 URL
        base = (config.openai_base_url or "").rstrip("/")
        if not base:
            raise ValueError("MIDSCENE_MODEL_BASE_URL is required")
        
        # 智能拼接 URL：
        # 1. 如果 base_url 已经包含版本路径（/v1, /v2, /v3 等），直接拼 /chat/completions
        # 2. 否则自动加 /v1/chat/completions（适用于反代）
        import re as _re
        if _re.search(r'/v\d+$', base):
            # 已经包含版本路径：/v1, /v3 等
            url = f"{base}/chat/completions"
        else:
            # 没有版本路径，自动加 /v1（适用于反代）
            url = f"{base}/v1/chat/completions"
        
        logger.debug(f"Request URL: {url}")

        # 构造请求头
        headers = {
            "Authorization": f"Bearer {config.openai_api_key}",
            "Content-Type": "application/json",
        }

        # 构造请求体
        data = {
            "model": config.model_name,
            "messages": messages,
            "max_tokens": 4096,
        }

        # temperature 仅在非零时设置（有些 API 不支持）
        if config.temperature is not None and config.temperature > 0:
            data["temperature"] = config.temperature

        # 发送请求（trust_env=False 禁用系统代理）
        with httpx.Client(
            trust_env=False,
            timeout=config.timeout or 120
        ) as client:
            response = client.post(url, headers=headers, json=data)

        if response.status_code != 200:
            logger.error(f"API request failed: status={response.status_code}, body={response.text[:500]}")
            raise RuntimeError(
                f"API request failed (status {response.status_code}): {response.text[:200]}"
            )

        result = response.json()

        # 提取响应内容（OpenAI 格式）
        content = result["choices"][0]["message"]["content"]

        # 提取 usage 信息
        usage = None
        if "usage" in result:
            usage = {
                "prompt_tokens": result["usage"].get("prompt_tokens"),
                "completion_tokens": result["usage"].get("completion_tokens"),
                "total_tokens": result["usage"].get("total_tokens"),
            }

        return {
            "content": content,
            "usage": usage,
            "raw_response": result
        }

    async def ai_locate(
        self,
        prompt: str,
        use_cache: bool = True
    ) -> Optional[LocateResultElement]:
        """
        使用 AI 定位页面元素

        Args:
            prompt: 元素描述（如 "登录按钮"）
            use_cache: 是否使用缓存

        Returns:
            定位结果或 None
        """
        logger.info(f"AI Locate: '{prompt}'")

        # 开始记录步骤（SessionRecorder）
        if self.session_recorder:
            self.session_recorder.start_step("locate", prompt)

        # 开始记录任务（旧版兼容）
        if self.recorder:
            task = self.recorder.start_task("locate", param=prompt)

        # 检查缓存（与 JS 版本对齐：使用 XPath 定位）
        if use_cache and self.task_cache:
            cache_result = self.task_cache.match_locate_cache(prompt)
            if cache_result:
                logger.info(f"Cache hit for locate: '{prompt}'")
                cache_data = cache_result.cache_content.cache
                
                # JS 版本格式：使用 xpaths 定位元素
                if cache_data and "xpaths" in cache_data:
                    xpaths = cache_data["xpaths"]
                    if xpaths and len(xpaths) > 0:
                        xpath = xpaths[0]  # 使用第一个 XPath
                        logger.info(f"Using cached XPath: {xpath[:80]}...")
                        
                        # 通过 XPath 获取元素位置
                        element_info = await self.interface.get_element_by_xpath(xpath)
                        if element_info:
                            rect = element_info["rect"]
                            center = element_info["center"]
                            
                            element = LocateResultElement(
                                description=prompt,
                                center=center,
                                rect=rect
                            )
                            
                            logger.info(f"Cache hit (XPath): '{prompt}' at {center}")
                            
                            # 记录缓存命中
                            if self.recorder:
                                self.recorder.finish_task(status="finished", output=element)
                            if self.session_recorder:
                                self.session_recorder.complete_step("success")
                            
                            return element
                        else:
                            # XPath 找不到元素，可能页面结构变化，需要重新 AI 定位
                            logger.warning(f"Cached XPath not found on page, re-locating: '{prompt}'")

        # 获取截图
        screenshot_b64 = await self.interface.screenshot()
        size = await self.interface.get_size()

        # 记录截图（SessionRecorder）
        if self.session_recorder:
            self.session_recorder.record_screenshot_before(screenshot_b64)

        # 记录截图（旧版兼容）
        if self.recorder:
            screenshot_item = ScreenshotItem(screenshot_b64)
            self.recorder.record_screenshot(screenshot_item, timing="before")

        # 获取模型配置
        config = self._get_model_config(INTENT_DEFAULT)
        model_family = config.model_family or "qwen2.5-vl"

        # 准备消息
        messages = self._build_messages(
            system_prompt=system_prompt_to_locate_element(model_family),
            user_prompt=find_element_prompt(prompt),
            screenshot_b64=screenshot_b64
        )

        # 调用 AI
        start_time = time.time()
        result = self._call_ai_with_config(messages, INTENT_DEFAULT)
        elapsed_ms = (time.time() - start_time) * 1000

        # 记录 AI 使用信息
        if self.session_recorder and result.get('usage'):
            self.session_recorder.record_ai_info(
                model=config.model_name,
                tokens=result['usage'].get('total_tokens'),
                response=result.get('content', '')[:500]
            )

        if self.recorder and result.get('usage'):
            usage_info = result['usage'].copy()
            usage_info['time_cost'] = elapsed_ms / 1000
            usage_info['model_name'] = config.model_name
            self.recorder.record_ai_usage(usage_info)

        logger.info(
            f"AI locate completed: {elapsed_ms:.0f}ms, "
            f"tokens={result.get('usage', {}).get('total_tokens', 0) if result.get('usage') else 0}"
        )

        # 解析结果
        from ...shared.utils import safe_parse_json, extract_json_from_code_block
        # 先提取 JSON（处理 markdown 代码块）
        json_text = extract_json_from_code_block(result["content"])
        response_data = safe_parse_json(json_text)

        if not response_data or "bbox" not in response_data:
            logger.warning(f"AI locate failed: no bbox in response")
            if self.recorder:
                self.recorder.finish_task(status="failed", error=ValueError("No bbox in response"))
            if self.session_recorder:
                self.session_recorder.fail_step("No bbox in response")
            return None

        bbox = response_data["bbox"]
        if not bbox or (isinstance(bbox, list) and len(bbox) < 2):
            logger.warning(f"AI locate failed: invalid bbox {bbox}")
            if self.recorder:
                self.recorder.finish_task(status="failed", error=ValueError(f"Invalid bbox: {bbox}"))
            if self.session_recorder:
                self.session_recorder.fail_step(f"Invalid bbox: {bbox}")
            return None

        # 根据模型类型适配 bbox 坐标（关键：doubao 返回的是归一化 0-1000 坐标）
        model_family = config.model_family or "qwen2.5-vl"
        img_width = int(size.get('width', 1280))
        img_height = int(size.get('height', 800))
        
        try:
            adapted_bbox = adapt_bbox(
                bbox=bbox,
                width=img_width,
                height=img_height,
                right_limit=img_width,
                bottom_limit=img_height,
                model_family=model_family
            )
            logger.debug(f"Adapted bbox: {bbox} -> {adapted_bbox} (model={model_family}, size={img_width}x{img_height})")
        except Exception as e:
            logger.warning(f"Failed to adapt bbox: {e}, using raw values")
            adapted_bbox = tuple(bbox) if isinstance(bbox, list) else bbox

        # 转换为 Rect 和中心点
        rect = format_bbox(adapted_bbox)
        center = calculate_center(rect)

        element = LocateResultElement(
            description=prompt,
            center=center,
            rect=rect
        )

        # 记录元素定位结果（SessionRecorder - 带可视化标记）
        if self.session_recorder:
            bbox_tuple: Tuple[int, int, int, int] = (
                int(rect['left']),
                int(rect['top']),
                int(rect['left'] + rect['width']),
                int(rect['top'] + rect['height'])
            )
            center_tuple: Tuple[int, int] = (int(center[0]), int(center[1]))
            self.session_recorder.record_element_location(
                bbox=bbox_tuple,
                center=center_tuple,
                description=prompt,
                draw_marker=True
            )

        # 保存到缓存（与 JS 版本对齐：存储 XPath 而不是坐标）
        if use_cache and self.task_cache:
            # 获取元素的 XPath（通过元素中心点定位 DOM 元素）
            xpath = await self.interface.get_element_xpath(center[0], center[1])
            if xpath:
                self.task_cache.append_cache(LocateCache(
                    type="locate",
                    prompt=prompt,
                    cache={
                        "xpaths": [xpath]  # 与 JS 版本格式完全一致
                    }
                ))
                logger.debug(f"Cached XPath for '{prompt}': {xpath[:80]}...")
            else:
                logger.warning(f"Could not get XPath for element at {center}, cache not saved")

        # 完成任务记录
        if self.recorder:
            self.recorder.finish_task(status="finished", output=element)
        if self.session_recorder:
            self.session_recorder.complete_step("success")

        logger.info(f"Element located: {prompt} at {center}")

        return element

    async def ai_locate_with_scroll_retry(
        self,
        prompt: str,
        use_cache: bool = True,
        max_scroll_attempts: int = 3,
        scroll_distance: int = 500
    ) -> Optional[LocateResultElement]:
        """
        带滚动重试的智能元素定位（增强版）
        
        工作流程：
        1. 第1次：在当前视口尝试定位
        2. 失败 → 向下滚动 500px → 第2次尝试
        3. 失败 → 再次滚动 500px → 第3次尝试
        4. 找到元素后自动滚动到视口中心（与 JS 版本对齐）
        
        Args:
            prompt: 元素描述
            use_cache: 是否使用缓存（第一次尝试时使用，重试时不使用）
            max_scroll_attempts: 最大滚动尝试次数（默认3次）
            scroll_distance: 每次滚动距离（像素，默认500）
        
        Returns:
            定位结果或 None
        """
        logger.info(f"AI Locate with scroll retry: '{prompt}' (max_attempts={max_scroll_attempts})")
        
        for attempt in range(max_scroll_attempts):
            # 尝试定位元素
            # 第一次尝试使用缓存，后续重试不使用缓存（因为页面位置已改变）
            should_use_cache = use_cache and (attempt == 0)
            element = await self.ai_locate(prompt, use_cache=should_use_cache)
            
            if element:
                logger.info(
                    f"Element '{prompt}' found on attempt {attempt + 1}/{max_scroll_attempts} "
                    f"at {element.center}"
                )
                return element
            
            # 如果还有重试机会，滚动页面
            if attempt < max_scroll_attempts - 1:
                logger.info(
                    f"Element '{prompt}' not found in current viewport, "
                    f"scrolling down {scroll_distance}px (attempt {attempt + 1}/{max_scroll_attempts})"
                )
                
                # 滚动页面
                await self.interface.scroll('down', scroll_distance)
                
                # 等待页面稳定
                await asyncio.sleep(0.5)
        
        logger.warning(
            f"Element '{prompt}' not found after {max_scroll_attempts} scroll attempts"
        )
        return None

    async def ai_click(self, prompt: str, enable_scroll_retry: bool = True) -> bool:
        """
        使用 AI 定位并点击元素

        Args:
            prompt: 元素描述
            enable_scroll_retry: 是否启用滚动重试（默认 True）

        Returns:
            是否成功
        """
        # 开始记录步骤（SessionRecorder）
        if self.session_recorder:
            self.session_recorder.start_step("click", prompt)
            # 获取操作前截图
            screenshot_before = await self.interface.screenshot()
            self.session_recorder.record_screenshot_before(screenshot_before)

        # 开始记录任务（旧版兼容）
        if self.recorder:
            task = self.recorder.start_task("click", param=prompt)

        # 🔑 使用滚动重试机制定位元素
        if enable_scroll_retry:
            element = await self.ai_locate_with_scroll_retry(prompt)
        else:
            element = await self.ai_locate(prompt)
        
        if not element:
            logger.error(f"Cannot locate element: {prompt}")
            if self.recorder:
                self.recorder.finish_task(status="failed", error=ValueError(f"Cannot locate: {prompt}"))
            if self.session_recorder:
                self.session_recorder.fail_step(f"Cannot locate: {prompt}")
            return False

        # 记录元素位置
        if self.session_recorder:
            rect = element.rect
            bbox_tuple: Tuple[int, int, int, int] = (
                int(rect['left']),
                int(rect['top']),
                int(rect['left'] + rect['width']),
                int(rect['top'] + rect['height'])
            )
            center_tuple: Tuple[int, int] = (int(element.center[0]), int(element.center[1]))
            self.session_recorder.record_element_location(
                bbox=bbox_tuple,
                center=center_tuple,
                description=prompt,
                draw_marker=True
            )

        # 点击中心点
        x, y = element.center
        await self.interface.click(x, y)

        # 获取操作后截图
        if self.session_recorder:
            screenshot_after = await self.interface.screenshot()
            self.session_recorder.record_screenshot_after(screenshot_after)
            self.session_recorder.complete_step("success")

        logger.info(f"Clicked: {prompt} at ({x}, {y})")

        # 完成任务记录
        if self.recorder:
            self.recorder.finish_task(status="finished", output={"x": x, "y": y})

        return True

    async def ai_input(self, prompt: str, text: str, enable_scroll_retry: bool = True) -> bool:
        """
        使用 AI 定位并输入文本

        Args:
            prompt: 元素描述
            text: 要输入的文本
            enable_scroll_retry: 是否启用滚动重试（默认 True）

        Returns:
            是否成功
        """
        # 开始记录步骤（SessionRecorder）
        if self.session_recorder:
            self.session_recorder.start_step("input", f"{prompt}: {text}")
            screenshot_before = await self.interface.screenshot()
            self.session_recorder.record_screenshot_before(screenshot_before)

        # 开始记录任务（旧版兼容）
        if self.recorder:
            task = self.recorder.start_task("input", param={"prompt": prompt, "text": text})

        # 🔑 使用滚动重试机制定位元素
        if enable_scroll_retry:
            element = await self.ai_locate_with_scroll_retry(prompt)
        else:
            element = await self.ai_locate(prompt)
        
        if not element:
            logger.error(f"Cannot locate element: {prompt}")
            if self.recorder:
                self.recorder.finish_task(status="failed", error=ValueError(f"Cannot locate: {prompt}"))
            if self.session_recorder:
                self.session_recorder.fail_step(f"Cannot locate: {prompt}")
            return False

        # 点击并输入
        x, y = element.center
        await self.interface.input_text(text, x, y)

        # 获取操作后截图
        if self.session_recorder:
            screenshot_after = await self.interface.screenshot()
            self.session_recorder.record_screenshot_after(screenshot_after)
            self.session_recorder.complete_step("success")

        logger.info(f"Input to {prompt}: '{text}'")

        # 完成任务记录
        if self.recorder:
            self.recorder.finish_task(status="finished", output={"text": text})

        return True

    async def ai_query(
        self,
        data_demand: Union[Dict[str, str], str],
        use_cache: bool = False
    ) -> Dict[str, Any]:
        """
        使用 AI 从页面提取数据

        Args:
            data_demand: 数据需求（字典或字符串）
            use_cache: 是否使用缓存

        Returns:
            提取的数据
        """
        logger.info(f"AI Query: {data_demand}")

        # 开始记录任务
        if self.recorder:
            task = self.recorder.start_task("query", param=data_demand)

        # 获取截图
        screenshot_b64 = await self.interface.screenshot()

        # 记录截图
        if self.recorder:
            screenshot_item = ScreenshotItem(screenshot_b64)
            self.recorder.record_screenshot(screenshot_item, timing="before")

        # 准备消息
        messages = self._build_messages(
            system_prompt=system_prompt_to_extract(),
            user_prompt=extract_data_prompt(data_demand),
            screenshot_b64=screenshot_b64
        )

        # 调用 AI
        start_time = time.time()
        config = self._get_model_config(INTENT_DEFAULT)
        result = self._call_ai_with_config(messages, INTENT_DEFAULT)
        elapsed_ms = (time.time() - start_time) * 1000

        # 记录 AI 使用信息
        if self.recorder and result.get('usage'):
            usage_info = result['usage'].copy()
            usage_info['time_cost'] = elapsed_ms / 1000
            usage_info['model_name'] = config.model_name
            self.recorder.record_ai_usage(usage_info)

        logger.info(
            f"AI query completed: {elapsed_ms:.0f}ms, "
            f"tokens={result.get('usage', {}).get('total_tokens', 0) if result.get('usage') else 0}"
        )

        # 解析 XML 响应
        try:
            parsed = parse_xml_extraction_response(result["content"])
            logger.info(f"Data extracted: {parsed['data']}")

            # 完成任务记录
            if self.recorder:
                self.recorder.finish_task(status="finished", output=parsed)

            return parsed
        except Exception as e:
            logger.error(f"Failed to parse extraction response: {e}")
            if self.recorder:
                self.recorder.finish_task(status="failed", error=e)
            raise

    async def ai_assert(
        self,
        assertion: str,
        message: str = ""
    ) -> bool:
        """
        使用 AI 断言页面状态

        Args:
            assertion: 断言描述（如 "页面显示登录成功"）
            message: 错误消息

        Returns:
            断言是否通过

        Raises:
            AssertionError: 如果断言失败
        """
        logger.info(f"AI Assert: '{assertion}'")

        # 开始记录任务
        if self.recorder:
            task = self.recorder.start_task("assert", param=assertion)

        # 获取截图
        screenshot_b64 = await self.interface.screenshot()

        # 记录截图
        if self.recorder:
            screenshot_item = ScreenshotItem(screenshot_b64)
            self.recorder.record_screenshot(screenshot_item, timing="before")

        # 准备消息
        messages = self._build_messages(
            system_prompt='You are an AI assistant that verifies UI states. Return JSON: {"pass": true/false, "thought": "reasoning"}',
            user_prompt=f"Verify: {assertion}",
            screenshot_b64=screenshot_b64
        )

        # 调用 AI
        start_time = time.time()
        config = self._get_model_config(INTENT_DEFAULT)
        result = self._call_ai_with_config(messages, INTENT_DEFAULT)
        elapsed_ms = (time.time() - start_time) * 1000

        # 记录 AI 使用信息
        if self.recorder and result.get('usage'):
            usage_info = result['usage'].copy()
            usage_info['time_cost'] = elapsed_ms / 1000
            usage_info['model_name'] = config.model_name
            self.recorder.record_ai_usage(usage_info)

        # 解析结果
        from ...shared.utils import safe_parse_json
        response_data = safe_parse_json(result["content"])

        if not response_data:
            error = ValueError("Failed to parse assertion response")
            if self.recorder:
                self.recorder.finish_task(status="failed", error=error)
            raise error

        passed = response_data.get("pass", False)
        thought = response_data.get("thought", "")

        if passed:
            logger.info(f"Assertion passed: {assertion}")
            if self.recorder:
                self.recorder.finish_task(status="finished", output={"pass": True, "thought": thought})
            return True
        else:
            error_msg = message or f"Assertion failed: {assertion}\nReason: {thought}"
            logger.error(error_msg)
            if self.recorder:
                self.recorder.finish_task(status="failed", error=AssertionError(error_msg))
            raise AssertionError(error_msg)

    async def ai_act(
        self,
        task_prompt: str,
        use_cache: bool = True
    ) -> bool:
        """
        使用 AI 执行复杂任务（简化版）

        Args:
            task_prompt: 任务描述
            use_cache: 是否使用缓存

        Returns:
            是否成功
        """
        logger.info(f"AI Act: '{task_prompt}'")

        # 这是简化版实现
        # 完整实现需要：
        # 1. 任务规划（生成 YAML 工作流）
        # 2. 任务执行器（执行每个步骤）
        # 3. 错误处理和重试

        # 目前仅作为示例，实际应该调用规划和执行逻辑
        logger.warning("ai_act is simplified version, full implementation pending")

        return True

    def get_cache_stats(self) -> Optional[Dict[str, Any]]:
        """获取缓存统计信息"""
        if self.task_cache:
            return self.task_cache.get_stats()
        return None

    def finish(self) -> Optional[str]:
        """
        结束会话并生成报告

        Returns:
            报告文件路径（如果启用了记录）
        """
        if self.session_recorder:
            report_path = self.session_recorder.finish()
            logger.info(f"Session finished, report saved to: {report_path}")
            return report_path
        return None

    def save_report(self) -> Optional[str]:
        """
        手动保存报告

        Returns:
            报告文件路径
        """
        if self.session_recorder:
            return self.session_recorder.save_report()
        return None

    def get_report_dir(self) -> Optional[str]:
        """获取报告目录路径"""
        if self.session_recorder:
            return str(self.session_recorder.run_manager.report_dir)
        return None

    async def __aenter__(self):
        """异步上下文管理器入口"""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器退出 - 自动保存报告"""
        if exc_type and self.session_recorder:
            # 如果有异常，标记当前步骤失败
            if self.session_recorder.current_step:
                self.session_recorder.fail_step(str(exc_val))

        self.finish()
        return False


__all__ = ["Agent"]
