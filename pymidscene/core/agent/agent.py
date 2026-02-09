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

        # 发送请求（带重试机制，处理中转服务临时不可用）
        # 可重试的 HTTP 状态码：429(限流), 500, 502, 503(服务不可用), 504
        retryable_status_codes = {429, 500, 502, 503, 504}
        max_retries = 3
        last_response = None

        for attempt in range(max_retries + 1):
            with httpx.Client(
                trust_env=False,
                timeout=config.timeout or 120
            ) as client:
                last_response = client.post(url, headers=headers, json=data)

            if last_response.status_code == 200:
                break

            if last_response.status_code in retryable_status_codes and attempt < max_retries:
                wait_time = 2 ** attempt  # 指数退避: 1s, 2s, 4s
                logger.warning(
                    f"API request failed (status {last_response.status_code}), "
                    f"retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})... "
                    f"body={last_response.text[:200]}"
                )
                import time as _time
                _time.sleep(wait_time)
                continue

            # 不可重试的错误，直接抛出
            break

        response = last_response
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
        max_scroll_attempts: int = 5,
        scroll_distance: int = 500
    ) -> Optional[LocateResultElement]:
        """
        带滚动重试的智能元素定位（增强版，与 JS 版本对齐）
        
        工作流程（双向搜索）：
        1. 第1次：在当前视口尝试定位
        2. 失败 → 向下滚动 → 重试（最多尝试 max_scroll_attempts 次向下滚动）
        3. 所有向下尝试失败 → 回到顶部 → 向下逐步搜索（覆盖页面上方区域）
        4. 找到元素后通过 XPath scrollIntoView 自动滚动到视口中心
        
        对应 JS 版本:
        - locator.ts: getElementInfoByXpath 中的 scrollIntoView 机制
        - tasks.ts: AI replanning loop 中的 Scroll action
        
        Args:
            prompt: 元素描述
            use_cache: 是否使用缓存（第一次尝试时使用，重试时不使用）
            max_scroll_attempts: 最大滚动尝试次数（默认5次，覆盖 2500px）
            scroll_distance: 每次滚动距离（像素，默认500）
        
        Returns:
            定位结果或 None
        """
        logger.info(f"AI Locate with scroll retry: '{prompt}' (max_attempts={max_scroll_attempts})")
        
        # 阶段 1: 当前位置 + 向下滚动搜索
        for attempt in range(max_scroll_attempts):
            should_use_cache = use_cache and (attempt == 0)
            element = await self.ai_locate(prompt, use_cache=should_use_cache)
            
            if element:
                logger.info(
                    f"Element '{prompt}' found on attempt {attempt + 1}/{max_scroll_attempts} "
                    f"at {element.center}"
                )
                # 找到后尝试通过 XPath scrollIntoView（与 JS locator.ts 对齐）
                await self._scroll_element_into_view_after_locate(element)
                return element
            
            if attempt < max_scroll_attempts - 1:
                logger.info(
                    f"Element '{prompt}' not found in current viewport, "
                    f"scrolling down {scroll_distance}px (attempt {attempt + 1}/{max_scroll_attempts})"
                )
                await self.interface.scroll('down', scroll_distance)
                await asyncio.sleep(0.5)
        
        # 阶段 2: 回到顶部，向下搜索上方区域
        logger.info(f"Element '{prompt}' not found scrolling down, trying from top of page")
        try:
            await self.interface.evaluate_javascript("window.scrollTo(0, 0)")
            await asyncio.sleep(0.5)
            
            # 从顶部再做 2 次尝试
            for attempt in range(2):
                element = await self.ai_locate(prompt, use_cache=False)
                if element:
                    logger.info(f"Element '{prompt}' found from top on attempt {attempt + 1}")
                    await self._scroll_element_into_view_after_locate(element)
                    return element
                
                if attempt < 1:
                    await self.interface.scroll('down', scroll_distance)
                    await asyncio.sleep(0.5)
        except Exception as e:
            logger.warning(f"Scroll-to-top search failed: {e}")
        
        logger.warning(
            f"Element '{prompt}' not found after {max_scroll_attempts + 2} total scroll attempts"
        )
        return None

    async def _scroll_element_into_view_after_locate(
        self,
        element: LocateResultElement
    ) -> None:
        """
        定位到元素后，通过 XPath scrollIntoView 确保元素在视口中心
        
        对应 JS 版本: locator.ts getElementInfoByXpath 中的
        node.scrollIntoView({ behavior: 'instant', block: 'center' })
        """
        try:
            # 获取元素的 XPath
            xpath = await self.interface.get_element_xpath(
                element.center[0], element.center[1]
            )
            if xpath:
                # 通过 XPath 滚动到视口中心（与 JS 完全一致）
                scrolled = await self.interface.scroll_element_by_xpath_into_view(xpath)
                if scrolled:
                    logger.debug(f"Element scrolled into view via XPath")
                    # 滚动后需要重新获取坐标
                    element_info = await self.interface.get_element_by_xpath(xpath)
                    if element_info:
                        element.center = tuple(element_info["center"])
                        element.rect = element_info["rect"]
        except Exception as e:
            logger.debug(f"XPath scrollIntoView skipped: {e}")

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

        # 准备消息（与 JS 版本 assert prompt 对齐）
        # JS 版本的断言标准：只要屏幕上可见该内容即为 pass，不要求是"当前活动页面"
        system_prompt = (
            "You are an AI assistant that verifies UI states based on screenshots.\n"
            "Look at the screenshot carefully and determine whether the given assertion is true or false.\n"
            "\n"
            "IMPORTANT: The assertion passes as long as the described content is VISIBLE ANYWHERE on the screen.\n"
            "It does NOT need to be the main/active content, the focused element, or the primary page.\n"
            "If the text, element, or UI component mentioned in the assertion can be seen anywhere in the screenshot\n"
            "(including sidebars, menus, headers, footers, tabs, etc.), the assertion is TRUE.\n"
            "\n"
            "You MUST return a valid JSON object (no markdown, no code blocks) with exactly this format:\n"
            '{"pass": true, "thought": "your reasoning"}\n'
            "or\n"
            '{"pass": false, "thought": "your reasoning"}\n'
            "Rules:\n"
            '- "pass" must be a boolean (true or false)\n'
            '- "thought" must be a string explaining your reasoning\n'
            "- Do NOT wrap the JSON in markdown code blocks\n"
            "- Do NOT include any other text outside the JSON object"
        )
        messages = self._build_messages(
            system_prompt=system_prompt,
            user_prompt=f"Verify this assertion about the current page: {assertion}",
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

        # 解析结果（先提取 JSON，处理模型返回 markdown 代码块的情况）
        from ...shared.utils import safe_parse_json, extract_json_from_code_block
        raw_content = result["content"]
        json_text = extract_json_from_code_block(raw_content)
        response_data = safe_parse_json(json_text)

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
        使用 AI 执行复杂任务 — 完整的 plan-execute-replan 循环（带缓存）

        对应 JS 版本: agent.ts aiAct + tasks.ts runAction()

        缓存机制（与 JS 版本对齐）：
        1. 首次执行：AI 规划 → 执行 → 将动作序列保存到缓存（YAML workflow）
        2. 后续执行：直接从缓存读取动作序列并回放（跳过 AI 调用）

        核心机制：
        1. 截图发给 AI，AI 根据当前页面状态规划动作（包括 Scroll）
        2. 执行 AI 规划的动作序列
        3. 如果 AI 返回 shouldContinuePlanning=true，重新截图并 replan
        4. 循环直到任务完成或达到最大重规划次数

        Args:
            task_prompt: 任务描述（如 "点击自主声明选项的下拉选择框"）
            use_cache: 是否使用缓存

        Returns:
            是否成功
        """
        from ..ai_model.prompts.planner import (
            system_prompt_to_plan,
            plan_task_prompt,
            parse_planning_response,
        )

        logger.info(f"AI Act: '{task_prompt}'")

        # 开始记录步骤
        if self.session_recorder:
            self.session_recorder.start_step("act", task_prompt)

        if self.recorder:
            self.recorder.start_task("act", param=task_prompt)

        # ==================== 缓存读取（与 JS 版本对齐） ====================
        # JS 版本: agent.ts aiAct 中的 cache 逻辑
        if use_cache and self.task_cache:
            cache_result = self.task_cache.match_plan_cache(task_prompt)
            if cache_result:
                cached_plan = cache_result.cache_content
                if hasattr(cached_plan, 'yaml_workflow') and cached_plan.yaml_workflow:
                    logger.info(f"Cache hit for ai_act: '{task_prompt}'")
                    try:
                        success = await self._replay_cached_plan(
                            cached_plan.yaml_workflow
                        )
                        if self.recorder:
                            self.recorder.finish_task(
                                status="finished" if success else "failed"
                            )
                        if self.session_recorder:
                            if success:
                                screenshot_after = await self.interface.screenshot()
                                self.session_recorder.record_screenshot_after(screenshot_after)
                                self.session_recorder.complete_step("success (cached)")
                            else:
                                self.session_recorder.fail_step("cached plan replay failed")
                        return success
                    except Exception as e:
                        logger.warning(
                            f"Cached plan replay failed, falling back to AI: {e}"
                        )
                        # 缓存回放失败，继续走正常 AI 规划流程

        # ==================== 正常 AI 规划流程 ====================
        max_replan_cycles = 10  # 对应 JS: replanningCycleLimit
        replan_count = 0
        conversation_history: List[str] = []
        all_executed_actions: List[Dict[str, Any]] = []  # 收集所有执行的动作，用于缓存

        try:
            while True:
                # 1. 截图 + 获取页面信息
                screenshot_b64 = await self.interface.screenshot()
                size = await self.interface.get_size()

                if self.session_recorder:
                    self.session_recorder.record_screenshot_before(screenshot_b64)

                # 2. 调用 AI 规划
                messages = self._build_messages(
                    system_prompt=system_prompt_to_plan(),
                    user_prompt=plan_task_prompt(task_prompt, conversation_history or None),
                    screenshot_b64=screenshot_b64
                )

                start_time = time.time()
                config = self._get_model_config(INTENT_DEFAULT)
                result = self._call_ai_with_config(messages, INTENT_DEFAULT)
                elapsed_ms = (time.time() - start_time) * 1000

                logger.info(
                    f"AI planning completed: {elapsed_ms:.0f}ms, "
                    f"tokens={result.get('usage', {}).get('total_tokens', 0) if result.get('usage') else 0}"
                )

                # 记录 AI 使用
                if self.recorder and result.get('usage'):
                    usage_info = result['usage'].copy()
                    usage_info['time_cost'] = elapsed_ms / 1000
                    usage_info['model_name'] = config.model_name
                    self.recorder.record_ai_usage(usage_info)

                if self.session_recorder and result.get('usage'):
                    self.session_recorder.record_ai_info(
                        model=config.model_name,
                        tokens=result['usage'].get('total_tokens'),
                        response=result.get('content', '')[:500]
                    )

                # 3. 解析规划结果
                try:
                    plan_result = parse_planning_response(result["content"])
                except Exception as e:
                    logger.error(f"Failed to parse planning response: {e}")
                    logger.debug(f"Raw response: {result['content'][:500]}")
                    # 解析失败时尝试回退：作为单步 click 处理
                    conversation_history.append(f"Planning parse error: {e}")
                    if replan_count >= 2:
                        # 如果连续解析失败，回退到 ai_click
                        logger.info(f"Falling back to ai_click for: '{task_prompt}'")
                        click_result = await self.ai_click(task_prompt)
                        if self.recorder:
                            self.recorder.finish_task(
                                status="finished" if click_result else "failed"
                            )
                        if self.session_recorder:
                            if click_result:
                                self.session_recorder.complete_step("success (fallback)")
                            else:
                                self.session_recorder.fail_step("fallback click failed")
                        return click_result
                    replan_count += 1
                    continue

                actions = plan_result.get("actions", [])
                should_continue = plan_result.get("shouldContinuePlanning", False)

                if not actions:
                    logger.warning("AI returned empty action plan")
                    conversation_history.append("No actions planned")
                    if replan_count >= 2:
                        break
                    replan_count += 1
                    continue

                # 4. 执行每个规划的动作
                for action in actions:
                    action_type = action.get("type", "")
                    param = action.get("param", {})
                    thought = action.get("thought", "")

                    logger.info(f"Executing action: {action_type} - {thought}")
                    conversation_history.append(
                        f"Executed: {action_type} ({thought})"
                    )

                    # 收集动作用于缓存
                    all_executed_actions.append(action)

                    success = await self._execute_planned_action(
                        action_type, param
                    )

                    if not success:
                        logger.warning(
                            f"Action failed: {action_type} with param {param}"
                        )
                        conversation_history.append(
                            f"Action failed: {action_type}"
                        )

                # 5. 检查是否需要继续规划
                if not should_continue:
                    logger.info(f"AI Act completed: '{task_prompt}'")
                    break

                # 6. Replan
                replan_count += 1
                if replan_count > max_replan_cycles:
                    logger.error(
                        f"Max replan cycles ({max_replan_cycles}) exceeded "
                        f"for task: '{task_prompt}'"
                    )
                    break

                logger.info(
                    f"Replanning (cycle {replan_count}/{max_replan_cycles})"
                )
                # 等待页面稳定后再截图
                await asyncio.sleep(0.5)

            # ==================== 缓存写入（与 JS 版本对齐） ====================
            if use_cache and self.task_cache and all_executed_actions:
                yaml_workflow = self._actions_to_yaml_workflow(all_executed_actions)
                self.task_cache.append_cache(PlanningCache(
                    type="plan",
                    prompt=task_prompt,
                    yaml_workflow=yaml_workflow
                ))
                logger.info(
                    f"Cached plan for '{task_prompt}': "
                    f"{len(all_executed_actions)} actions"
                )

            # 记录完成
            if self.session_recorder:
                screenshot_after = await self.interface.screenshot()
                self.session_recorder.record_screenshot_after(screenshot_after)
                self.session_recorder.complete_step("success")

            if self.recorder:
                self.recorder.finish_task(status="finished")

            return True

        except Exception as e:
            logger.error(f"AI Act failed: {e}")
            if self.recorder:
                self.recorder.finish_task(status="failed", error=e)
            if self.session_recorder:
                self.session_recorder.fail_step(str(e))
            raise

    # 别名，与 JS 版本的 aiAction 对齐
    ai_action = ai_act

    def _actions_to_yaml_workflow(self, actions: List[Dict[str, Any]]) -> str:
        """
        将动作列表序列化为 YAML workflow 字符串（用于缓存）

        对应 JS 版本: agent.ts 中 yamlFlow 的序列化逻辑

        Args:
            actions: 执行过的动作列表

        Returns:
            YAML 格式的 workflow 字符串
        """
        import yaml

        # 构建与 JS 版本兼容的 workflow 结构
        workflow = []
        for action in actions:
            step = {
                "type": action.get("type", ""),
                "param": action.get("param", {}),
            }
            thought = action.get("thought", "")
            if thought:
                step["thought"] = thought
            workflow.append(step)

        return yaml.dump(
            workflow,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False
        )

    async def _replay_cached_plan(self, yaml_workflow: str) -> bool:
        """
        回放缓存的动作序列（跳过 AI 调用）

        对应 JS 版本: agent.ts 中的 runYaml() 逻辑

        Args:
            yaml_workflow: YAML 格式的 workflow 字符串

        Returns:
            是否全部成功
        """
        import yaml

        try:
            actions = yaml.safe_load(yaml_workflow)
            if not isinstance(actions, list):
                logger.warning(f"Cached workflow is not a list: {type(actions)}")
                return False

            logger.info(f"Replaying cached plan: {len(actions)} actions")

            all_success = True
            for i, action in enumerate(actions):
                action_type = action.get("type", "")
                param = action.get("param", {})
                thought = action.get("thought", "")

                logger.info(
                    f"Replay action {i + 1}/{len(actions)}: "
                    f"{action_type} - {thought}"
                )

                success = await self._execute_planned_action(action_type, param)
                if not success:
                    logger.warning(f"Replay action failed: {action_type}")
                    all_success = False

            return all_success

        except Exception as e:
            logger.error(f"Failed to replay cached plan: {e}")
            return False

    async def _execute_planned_action(
        self,
        action_type: str,
        param: Dict[str, Any]
    ) -> bool:
        """
        执行 AI 规划的单个动作

        对应 JS 版本: tasks.ts 的 convertPlanToExecutable + 执行逻辑

        支持的动作类型（与 JS device/index.ts 对齐）：
        - Tap: 点击元素
        - Input: 输入文本
        - Hover: 悬停
        - Scroll: 滚动页面
        - KeyboardPress: 按键
        - Sleep: 等待
        - Assert: 断言

        Args:
            action_type: 动作类型
            param: 动作参数

        Returns:
            是否成功
        """
        try:
            action_upper = action_type.strip()

            if action_upper in ("Tap", "tap", "Click", "click"):
                prompt = param.get("prompt", param.get("locate", ""))
                if not prompt:
                    logger.warning(f"Tap action missing prompt/locate param")
                    return False
                return await self.ai_click(prompt)

            elif action_upper in ("Input", "input", "Type", "type"):
                prompt = param.get("prompt", param.get("locate", ""))
                value = param.get("value", param.get("text", ""))
                if not prompt or not value:
                    logger.warning(f"Input action missing prompt or value")
                    return False
                return await self.ai_input(prompt, value)

            elif action_upper in ("Hover", "hover"):
                prompt = param.get("prompt", param.get("locate", ""))
                if not prompt:
                    return False
                element = await self.ai_locate_with_scroll_retry(prompt)
                if element:
                    await self.interface.hover(element.center[0], element.center[1])
                    return True
                return False

            elif action_upper in ("Scroll", "scroll"):
                direction = param.get("direction", "down")
                distance = param.get("distance", 500)
                scroll_type = param.get("scrollType", "singleAction")

                if scroll_type == "scrollToBottom":
                    # 多次向下滚动
                    for _ in range(20):
                        await self.interface.scroll("down", 800)
                        await asyncio.sleep(0.3)
                elif scroll_type == "scrollToTop":
                    await self.interface.evaluate_javascript(
                        "window.scrollTo(0, 0)"
                    )
                    await asyncio.sleep(0.3)
                else:
                    # singleAction
                    await self.interface.scroll(direction, distance)
                    await asyncio.sleep(0.5)
                return True

            elif action_upper in ("KeyboardPress", "keyboardPress", "KeyPress", "keyPress"):
                key_name = param.get("keyName", param.get("key", ""))
                if not key_name:
                    return False
                await self.interface.key_press(key_name)
                return True

            elif action_upper in ("Sleep", "sleep", "Wait", "wait"):
                time_ms = param.get("timeMs", param.get("time", 1000))
                await asyncio.sleep(time_ms / 1000)
                return True

            elif action_upper in ("Assert", "assert"):
                condition = param.get("condition", param.get("assertion", ""))
                if condition:
                    try:
                        await self.ai_assert(condition)
                        return True
                    except AssertionError:
                        return False
                return True

            else:
                logger.warning(f"Unknown action type: {action_type}")
                return False

        except Exception as e:
            logger.error(f"Error executing action {action_type}: {e}")
            return False

    async def ai_wait_for(
        self,
        assertion: str,
        timeout: float = 30,
        interval: float = 2
    ) -> bool:
        """
        等待页面满足某个条件（轮询实现）

        对应 JS 版本: agent.ts 的 aiWaitFor / tasks.ts 的 waitFor

        Args:
            assertion: 断言条件描述（如 "页面显示了笔记管理"）
            timeout: 超时时间（秒）
            interval: 轮询间隔（秒）

        Returns:
            条件是否满足

        Raises:
            TimeoutError: 超时未满足条件
        """
        logger.info(f"AI WaitFor: '{assertion}' (timeout={timeout}s)")

        if self.session_recorder:
            self.session_recorder.start_step("waitFor", assertion)

        start = time.time()
        last_error = None

        while time.time() - start < timeout:
            try:
                await self.ai_assert(assertion)
                logger.info(f"WaitFor condition met: '{assertion}'")
                if self.session_recorder:
                    self.session_recorder.complete_step("success")
                return True
            except (AssertionError, Exception) as e:
                last_error = e
                logger.debug(
                    f"WaitFor condition not met yet: {e}, "
                    f"retrying in {interval}s..."
                )
                await asyncio.sleep(interval)

        error_msg = (
            f"WaitFor timeout ({timeout}s): {assertion}. "
            f"Last error: {last_error}"
        )
        logger.error(error_msg)
        if self.session_recorder:
            self.session_recorder.fail_step(error_msg)
        raise TimeoutError(error_msg)

    async def ai_scroll(
        self,
        direction: str = "down",
        distance: int = 500,
        scroll_type: str = "singleAction",
        locate_prompt: Optional[str] = None
    ) -> bool:
        """
        AI 滚动操作

        对应 JS 版本: agent.ts 的 aiScroll

        Args:
            direction: 滚动方向（up/down/left/right）
            distance: 滚动距离（像素）
            scroll_type: 滚动类型
                - singleAction: 单次滚动
                - scrollToBottom: 滚动到底部
                - scrollToTop: 滚动到顶部
            locate_prompt: 可选的元素描述，在该元素上滚动

        Returns:
            是否成功
        """
        logger.info(
            f"AI Scroll: direction={direction}, distance={distance}, "
            f"type={scroll_type}, locate={locate_prompt}"
        )

        if self.session_recorder:
            self.session_recorder.start_step(
                "scroll",
                f"{direction} {distance}px ({scroll_type})"
            )

        try:
            # 如果指定了元素，先定位到元素
            starting_point = None
            if locate_prompt:
                element = await self.ai_locate(locate_prompt)
                if element:
                    starting_point = element.center

            if scroll_type == "scrollToTop":
                await self.interface.evaluate_javascript(
                    "window.scrollTo(0, 0)"
                )
                await asyncio.sleep(0.3)
            elif scroll_type == "scrollToBottom":
                await self.interface.evaluate_javascript(
                    "window.scrollTo(0, document.body.scrollHeight)"
                )
                await asyncio.sleep(0.3)
            else:
                # singleAction
                if starting_point:
                    # 在特定元素上滚动（使用 mouse.wheel）
                    await self.interface.evaluate_javascript(f"""
                        (() => {{
                            const el = document.elementFromPoint(
                                {starting_point[0]}, {starting_point[1]}
                            );
                            if (el) {{
                                const deltaY = {distance if direction in ('down',) else -distance if direction == 'up' else 0};
                                const deltaX = {distance if direction == 'right' else -distance if direction == 'left' else 0};
                                el.scrollBy(deltaX, deltaY);
                            }}
                        }})()
                    """)
                else:
                    await self.interface.scroll(direction, distance)
                await asyncio.sleep(0.5)

            if self.session_recorder:
                screenshot_after = await self.interface.screenshot()
                self.session_recorder.record_screenshot_after(screenshot_after)
                self.session_recorder.complete_step("success")

            return True

        except Exception as e:
            logger.error(f"AI Scroll failed: {e}")
            if self.session_recorder:
                self.session_recorder.fail_step(str(e))
            return False

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
