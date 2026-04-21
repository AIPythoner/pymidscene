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
from ...shared.utils import (
    calculate_center,
    format_bbox,
    adapt_bbox,
    resize_image_base64,
    resize_image_base64_to_size,
)
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

    async def _capture_ai_screenshot(self) -> Tuple[str, Size]:
        """
        Capture a screenshot and normalize it to CSS-space dimensions
        before sending to the AI, matching JS `agent.ts:447-467`.

        On HiDPI (dpr > 1), Playwright's `page.screenshot()` returns an image at
        `viewport × dpr` pixels; feeding that directly to a pixel-pass-through
        VLM (qwen2.5-vl) makes the returned coordinates live in image-pixel
        space while `page.mouse.click` consumes CSS-pixel space — resulting in
        a systematic miss factor of `dpr`. Shrinking the screenshot to CSS
        dimensions first is what JS does and collapses both spaces to CSS.
        Returns (screenshot_b64_css_space, size).
        """
        screenshot_b64 = await self.interface.screenshot()
        size = await self.interface.get_size()
        dpr = float(size.get('dpr') or 1)
        css_width = int(size.get('width', 0))
        css_height = int(size.get('height', 0))

        if dpr != 1.0 and css_width > 0 and css_height > 0:
            try:
                screenshot_b64 = resize_image_base64_to_size(
                    screenshot_b64, css_width, css_height
                )
                logger.debug(
                    f"Normalized screenshot to CSS dims "
                    f"{css_width}x{css_height} (dpr={dpr})"
                )
            except Exception as exc:
                logger.warning(f"Screenshot CSS normalization failed: {exc}")

        return screenshot_b64, size

    async def _capture_recording_screenshot(self) -> str:
        """
        Capture a screenshot for report recording, normalized to CSS-space
        dimensions to stay consistent with `_capture_ai_screenshot` output.

        On HiDPI devices (notably Android, dpr=2/3), the raw screenshot is in
        physical pixels while `element.center` / `element.rect` live in CSS
        pixels. If the "after" screenshot stays at physical dims while the
        "before" one was shrunk to CSS dims (via `_capture_ai_screenshot`),
        the report animation mid-stream swaps its underlying image to a
        different natural size — the click-replay scale-back then uses the
        wrong origin and the image flies to the top-left corner.
        """
        screenshot_b64 = await self.interface.screenshot()
        try:
            size = await self.interface.get_size()
        except Exception as exc:
            logger.debug(f"get_size failed in recording capture: {exc}")
            return screenshot_b64

        dpr = float(size.get('dpr') or 1)
        css_width = int(size.get('width', 0))
        css_height = int(size.get('height', 0))

        if dpr != 1.0 and css_width > 0 and css_height > 0:
            try:
                screenshot_b64 = resize_image_base64_to_size(
                    screenshot_b64, css_width, css_height
                )
            except Exception as exc:
                logger.warning(f"Recording screenshot CSS normalization failed: {exc}")

        return screenshot_b64

    def _build_messages(
        self,
        system_prompt: str,
        user_prompt: str,
        screenshot_b64: str
    ) -> List[Dict[str, Any]]:
        """
        构建 AI 消息.

        截图固定用 `image/jpeg` MIME:`WebPage.screenshot()` 已改为 JPEG q=90
        (对齐 JS base-page.ts).如果未来有调用方塞 PNG 进来,OpenAI / 主流 VL
        API 对 MIME 不严格,JPEG 声明下传 PNG 数据通常也能解;严格场景可加
        sniff/switch.
        """
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
                            "url": f"data:image/jpeg;base64,{screenshot_b64}"
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

        根据 model_family 自动选择调用方式：
        - gemini: 使用 google-genai SDK（原生 Gemini 协议）
        - claude: 使用 anthropic SDK（原生 Messages API）
        - 其他: 使用 httpx 直接请求（OpenAI 兼容协议）
        """
        config = self._get_model_config(intent)

        if config.model_family == 'gemini':
            return self._call_with_gemini_sdk(config, messages)
        if config.model_family == 'claude':
            return self._call_with_anthropic_sdk(config, messages)
        return self._call_with_httpx(config, messages)

    def _call_with_anthropic_sdk(
        self,
        config: ModelConfig,
        messages: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        使用 anthropic SDK 调用 Claude(原生 Messages API).

        处理:
        - OpenAI 风格的 messages(含 image_url data-URL) → Anthropic content blocks
          ({"type":"image", "source":{"type":"base64","media_type":...,"data":...}})
        - system role 不进入 messages,而是顶层 `system` 字段
        - 返回 OpenAI 一致的 {content, usage, raw_response} 结构

        SDK 不在 pyproject 硬依赖;仅在 model_family=='claude' 时 lazy import,
        缺失会给出明确的 pip 安装提示.
        """
        try:
            import anthropic
        except ImportError as exc:
            raise RuntimeError(
                "Anthropic native protocol requires the `anthropic` package. "
                "Install with: pip install anthropic"
            ) from exc

        client_kwargs: Dict[str, Any] = {"api_key": config.openai_api_key}
        base_url = (config.openai_base_url or "").rstrip("/") or None
        if base_url:
            client_kwargs["base_url"] = base_url

        client = anthropic.Anthropic(**client_kwargs)

        system_text, anthropic_messages = self._convert_messages_to_anthropic(messages)

        logger.info(
            f"Calling Anthropic API: model={config.model_name}, "
            f"base_url={base_url or 'default'}"
        )

        response = client.messages.create(
            model=config.model_name,
            max_tokens=4096,
            system=system_text if system_text else anthropic.NOT_GIVEN,
            messages=anthropic_messages,
        )

        # 拼接所有 text block 为 content
        content_parts: List[str] = []
        for block in getattr(response, "content", []) or []:
            text = getattr(block, "text", None)
            if text:
                content_parts.append(text)
        content = "".join(content_parts)

        usage_obj = getattr(response, "usage", None)
        usage: Optional[Dict[str, Any]] = None
        if usage_obj is not None:
            prompt_tokens = getattr(usage_obj, "input_tokens", None)
            completion_tokens = getattr(usage_obj, "output_tokens", None)
            total = (prompt_tokens or 0) + (completion_tokens or 0)
            usage = {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total or None,
            }

        return {
            "content": content,
            "usage": usage,
            "raw_response": response,
        }

    def _convert_messages_to_anthropic(
        self,
        messages: List[Dict[str, Any]],
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Convert OpenAI-style messages to Anthropic's (system_text, messages[]) tuple.

        OpenAI system role is hoisted into Anthropic's top-level `system` field;
        `image_url` blocks with `data:image/...;base64,...` are rewritten into
        Anthropic image source blocks (`{type: image, source: {type: base64, ...}}`).
        Remote image URLs fall back to a text placeholder since anthropic SDK
        supports `{type: image, source: {type: url, url: ...}}` on newer versions
        but we keep the safest cross-version path here.
        """
        system_parts: List[str] = []
        converted: List[Dict[str, Any]] = []

        for msg in messages:
            role = msg.get("role", "user")
            raw_content = msg.get("content", "")

            if role == "system":
                if isinstance(raw_content, str):
                    system_parts.append(raw_content)
                elif isinstance(raw_content, list):
                    for item in raw_content:
                        if item.get("type") == "text":
                            system_parts.append(item.get("text", ""))
                continue

            target_role = "assistant" if role == "assistant" else "user"

            blocks: List[Dict[str, Any]] = []
            if isinstance(raw_content, str):
                blocks.append({"type": "text", "text": raw_content})
            elif isinstance(raw_content, list):
                for item in raw_content:
                    item_type = item.get("type")
                    if item_type == "text":
                        blocks.append({"type": "text", "text": item.get("text", "")})
                    elif item_type == "image_url":
                        url = (item.get("image_url") or {}).get("url", "") or ""
                        if url.startswith("data:") and "," in url:
                            header, data = url.split(",", 1)
                            mime = "image/png"
                            if ":" in header and ";" in header:
                                try:
                                    mime = header.split(":", 1)[1].split(";", 1)[0]
                                except Exception:
                                    pass
                            blocks.append({
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": mime,
                                    "data": data,
                                },
                            })
                        else:
                            blocks.append({
                                "type": "text",
                                "text": f"[image: {url}]",
                            })

            if blocks:
                converted.append({"role": target_role, "content": blocks})

        system_text = "\n\n".join(p for p in system_parts if p)
        return system_text, converted

    def _call_with_gemini_sdk(
        self,
        config: ModelConfig,
        messages: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        使用 google-genai SDK 调用 Gemini API（原生协议）
        
        自动处理：URL 拼接、认证、协议格式、重试
        支持：官方 API、中转站、反代 —— 只需配置 base_url
        """
        from google import genai
        from google.genai.types import HttpOptions

        base_url = (config.openai_base_url or "").rstrip("/")
        if not base_url:
            raise ValueError("MIDSCENE_MODEL_BASE_URL is required")

        client = genai.Client(
            api_key=config.openai_api_key,
            http_options=HttpOptions(base_url=base_url),
        )

        # 将 OpenAI 格式的 messages 转换为 Gemini contents 格式
        contents = self._convert_messages_to_gemini_contents(messages)

        logger.info(f"Calling Gemini API via google-genai SDK: model={config.model_name}, base_url={base_url}")

        response = client.models.generate_content(
            model=config.model_name,
            contents=contents,
        )

        content = response.text or ""
        usage = None
        if response.usage_metadata:
            usage = {
                "prompt_tokens": response.usage_metadata.prompt_token_count,
                "completion_tokens": response.usage_metadata.candidates_token_count,
                "total_tokens": response.usage_metadata.total_token_count,
            }

        return {
            "content": content,
            "usage": usage,
            "raw_response": None,
        }
    def _convert_messages_to_gemini_contents(
        self,
        messages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        将 OpenAI 格式的 messages 转换为 Gemini contents 格式
        
        OpenAI: [{role, content: str | [{type: text/image_url, ...}]}]
        Gemini: [{role, parts: [{text} | {inline_data: {mime_type, data}}]}]
        """
        contents = []
        for msg in messages:
            role = msg.get('role', 'user')
            if role == 'system':
                # Gemini 没有 system role，合并到 user
                role = 'user'
            elif role == 'assistant':
                role = 'model'
            raw_content = msg.get('content', '')
            parts = []
            if isinstance(raw_content, str):
                parts.append({'text': raw_content})
            elif isinstance(raw_content, list):
                for item in raw_content:
                    if item.get('type') == 'text':
                        parts.append({'text': item.get('text', '')})
                    elif item.get('type') == 'image_url':
                        image_url = item.get('image_url', {}).get('url', '')
                        if image_url.startswith('data:'):
                            # data:image/png;base64,xxxx
                            header, b64data = image_url.split(',', 1)
                            mime = header.split(':')[1].split(';')[0]
                            parts.append({
                                'inline_data': {
                                    'mime_type': mime,
                                    'data': b64data,
                                }
                            })
                        else:
                            parts.append({'text': f'[image: {image_url}]'})
            if parts:
                contents.append({'role': role, 'parts': parts})
        return contents

    def _call_with_httpx(
        self,
        config: ModelConfig,
        messages: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        使用 httpx 直接请求（OpenAI 兼容协议）
        
        适用于：豆包、千问等 OpenAI 兼容 API
        """
        import httpx

        base = (config.openai_base_url or "").rstrip("/")
        if not base:
            raise ValueError("MIDSCENE_MODEL_BASE_URL is required")
        import re as _re
        if _re.search(r'/v\d+[a-z]*$', base):
            url = f"{base}/chat/completions"
        else:
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

        # 发送请求(带重试机制,处理中转服务临时不可用)
        # 可重试:429/5xx + 传输层 ConnectError/ReadTimeout/ReadError(M7)
        retryable_status_codes = {429, 500, 502, 503, 504}
        max_retries = 3
        last_response: Optional["httpx.Response"] = None
        last_exc: Optional[Exception] = None

        import time as _time
        for attempt in range(max_retries + 1):
            try:
                with httpx.Client(
                    trust_env=False,
                    timeout=config.timeout or 120
                ) as client:
                    last_response = client.post(url, headers=headers, json=data)
                last_exc = None
            except (
                httpx.ConnectError,
                httpx.ReadTimeout,
                httpx.ReadError,
                httpx.RemoteProtocolError,
            ) as exc:
                last_exc = exc
                last_response = None
                if attempt < max_retries:
                    wait_time = 2 ** attempt
                    logger.warning(
                        f"Network error ({type(exc).__name__}: {exc}), "
                        f"retrying in {wait_time}s "
                        f"(attempt {attempt + 1}/{max_retries})..."
                    )
                    _time.sleep(wait_time)
                    continue
                break

            if last_response.status_code == 200:
                break

            if last_response.status_code in retryable_status_codes and attempt < max_retries:
                wait_time = 2 ** attempt
                logger.warning(
                    f"API request failed (status {last_response.status_code}), "
                    f"retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})... "
                    f"body={last_response.text[:200]}"
                )
                _time.sleep(wait_time)
                continue
            break

        if last_exc is not None and last_response is None:
            raise RuntimeError(
                f"API request failed (network error, {max_retries} retries exhausted): "
                f"{type(last_exc).__name__}: {last_exc}"
            ) from last_exc

        response = last_response
        assert response is not None
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
                        # M1: 多候选 fallback —— 遍历每条缓存的 XPath,首个解析到元素的就用
                        element_info = None
                        xpath = None
                        for candidate in xpaths:
                            info = await self.interface.get_element_by_xpath(candidate)
                            if info:
                                element_info = info
                                xpath = candidate
                                break
                        if xpath:
                            logger.info(f"Using cached XPath: {xpath[:80]}...")
                        if element_info:
                            rect = element_info["rect"]
                            center = element_info["center"]

                            element = LocateResultElement(
                                description=prompt,
                                center=center,
                                rect=rect
                            )

                            logger.info(f"Cache hit (XPath): '{prompt}' at {center}")

                            # 记录缓存命中 + 在 session_recorder 标记 hit_by(F2)
                            if self.recorder:
                                self.recorder.finish_task(status="finished", output=element)
                            if self.session_recorder:
                                self.session_recorder.record_cache_hit(
                                    cache_type="locate",
                                    xpath=xpath,
                                    prompt=prompt,
                                )
                                # 也把定位的 bbox/center 画到步骤截图上,方便回放
                                try:
                                    bbox_tuple: Tuple[int, int, int, int] = (
                                        int(rect['left']),
                                        int(rect['top']),
                                        int(rect['left'] + rect['width']),
                                        int(rect['top'] + rect['height']),
                                    )
                                    self.session_recorder.record_element_location(
                                        bbox=bbox_tuple,
                                        center=(int(center[0]), int(center[1])),
                                        description=prompt,
                                        draw_marker=True,
                                    )
                                except Exception:
                                    pass
                                self.session_recorder.complete_step("success (cached)")

                            return element
                        else:
                            # XPath 找不到元素，可能页面结构变化，需要重新 AI 定位
                            logger.warning(f"Cached XPath not found on page, re-locating: '{prompt}'")

        # 获取截图并归一化到 CSS 空间（HiDPI 对齐，与 JS agent.ts:447-467 一致）
        screenshot_b64, size = await self._capture_ai_screenshot()

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

        # 记录 AI 使用信息(含 token 细分,F1)
        if self.session_recorder and result.get('usage'):
            _usage = result['usage']
            self.session_recorder.record_ai_info(
                model=config.model_name,
                tokens=_usage.get('total_tokens'),
                prompt_tokens=_usage.get('prompt_tokens'),
                completion_tokens=_usage.get('completion_tokens'),
                response=result.get('content', '')[:2000],
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

        # 保存到缓存(与 JS 版本对齐:存储 XPath 而不是坐标)
        # 先跳过"第 3 行""最后一个"这类序数描述 —— 它们的 DOM 位置依赖当时的列表顺序,
        # 缓存 XPath 会在 DOM 重排后错点(order-sensitive judge 的离线启发版)。
        if use_cache and self.task_cache:
            from ..ai_model.prompts import heuristic_is_order_sensitive as _is_ord
            if _is_ord(prompt):
                logger.debug(
                    f"Skipping locate cache for order-sensitive prompt: '{prompt}'"
                )
            else:
                # M1: 生成多条 XPath 候选,提高 DOM 小改动时的 cache 命中率
                xpaths: List[str] = []
                if hasattr(self.interface, "get_element_xpaths"):
                    try:
                        xpaths = await self.interface.get_element_xpaths(
                            center[0], center[1]
                        ) or []
                    except Exception as exc:
                        logger.debug(f"get_element_xpaths failed: {exc}")
                if not xpaths:
                    single = await self.interface.get_element_xpath(center[0], center[1])
                    if single:
                        xpaths = [single]
                if xpaths:
                    self.task_cache.append_cache(LocateCache(
                        type="locate",
                        prompt=prompt,
                        cache={"xpaths": xpaths},
                    ))
                    logger.debug(
                        f"Cached {len(xpaths)} XPath(s) for '{prompt}': "
                        f"{xpaths[0][:80]}..."
                    )
                else:
                    logger.warning(
                        f"Could not get XPath for element at {center}, cache not saved"
                    )

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
        # F4:本调用内的 locate+click 两个子步骤合并到同一个 execution
        _click_group = None
        if self.session_recorder:
            _click_group = self.session_recorder.start_group(f"ai_click: {prompt}")

        # 开始记录步骤（SessionRecorder）
        if self.session_recorder:
            self.session_recorder.start_step("click", prompt)
            # 获取操作前截图
            screenshot_before = await self._capture_recording_screenshot()
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
                if _click_group:
                    self.session_recorder.end_group(_click_group)
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
            screenshot_after = await self._capture_recording_screenshot()
            self.session_recorder.record_screenshot_after(screenshot_after)
            self.session_recorder.complete_step("success")
            # F4:收尾本次 click 分组
            if _click_group:
                self.session_recorder.end_group(_click_group)

        logger.info(f"Clicked: {prompt} at ({x}, {y})")

        # 完成任务记录
        if self.recorder:
            self.recorder.finish_task(status="finished", output={"x": x, "y": y})

        return True

    async def ai_input(
        self,
        prompt: str,
        text: str,
        enable_scroll_retry: bool = True,
        mode: str = "replace",
    ) -> bool:
        """
        使用 AI 定位并输入文本.

        Args:
            prompt: 元素描述
            text: 要输入的文本
            enable_scroll_retry: 是否启用滚动重试(默认 True)
            mode: 输入模式(对齐 JS ``opt.mode``):
                - ``replace``(默认): 清空再输入
                - ``clear``: 只清空,不输入新内容(``text`` 会被忽略)
                - ``append`` / ``typeOnly``: 不清空,把 ``text`` 追加到当前内容

        Returns:
            是否成功
        """
        # F4:本调用内 locate+input 合并到同一 execution
        _input_group = None
        if self.session_recorder:
            _input_group = self.session_recorder.start_group(f"ai_input: {prompt}")

        # 开始记录步骤（SessionRecorder）
        if self.session_recorder:
            self.session_recorder.start_step("input", f"{prompt}: {text}")
            screenshot_before = await self._capture_recording_screenshot()
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
                if _input_group:
                    self.session_recorder.end_group(_input_group)
            return False

        # 点击并输入(M9: 支持 mode = replace / clear / append / typeOnly)
        x, y = element.center
        mode_normalised = (mode or "replace").strip().lower()
        if mode_normalised == "clear":
            # 只清空,不输入新内容
            await self.interface.input_text("", x, y, clear_first=True)
        elif mode_normalised in ("append", "typeonly"):
            # 不清空,把 text 追加进去
            await self.interface.input_text(text, x, y, clear_first=False)
        else:
            # replace (JS 默认)
            await self.interface.input_text(text, x, y, clear_first=True)

        # 获取操作后截图
        if self.session_recorder:
            screenshot_after = await self._capture_recording_screenshot()
            self.session_recorder.record_screenshot_after(screenshot_after)
            self.session_recorder.complete_step("success")
            if _input_group:
                self.session_recorder.end_group(_input_group)

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

        # M10: 在 SessionRecorder 上开一个 query 步骤,让前/后截图都能进报告
        if self.session_recorder:
            self.session_recorder.start_step("query", str(data_demand)[:200])

        # 开始记录任务(legacy)
        if self.recorder:
            task = self.recorder.start_task("query", param=data_demand)

        # 获取截图(CSS 归一化)
        screenshot_b64, _ = await self._capture_ai_screenshot()

        # 记录前截图
        if self.session_recorder:
            self.session_recorder.record_screenshot_before(screenshot_b64)
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

            # M10: 成功时附加 after 截图 + 完成步骤
            if self.session_recorder:
                try:
                    shot_after = await self._capture_recording_screenshot()
                    self.session_recorder.record_screenshot_after(shot_after)
                except Exception:
                    pass
                # 把 extracted data 挂到 step.ai_response 供报告展示
                try:
                    import json as _json
                    self.session_recorder.record_ai_info(
                        response=_json.dumps(parsed.get("data"))[:2000]
                    )
                except Exception:
                    pass
                self.session_recorder.complete_step("success")

            if self.recorder:
                self.recorder.finish_task(status="finished", output=parsed)

            return parsed
        except Exception as e:
            logger.error(f"Failed to parse extraction response: {e}")
            if self.session_recorder:
                self.session_recorder.fail_step(f"parse error: {e}")
            if self.recorder:
                self.recorder.finish_task(status="failed", error=e)
            raise

    async def ai_assert(
        self,
        assertion: str,
        message: str = "",
        keep_raw_response: bool = False,
    ) -> Union[bool, Dict[str, Any]]:
        """
        使用 AI 断言页面状态.

        对齐 JS agent.ts:1174-1248 的 `aiAssert` 契约.

        Args:
            assertion: 断言描述(如 "页面显示登录成功")
            message: 自定义错误消息
            keep_raw_response: 与 JS `opt.keepRawResponse` 对齐.
                当为 True 时,失败不抛出异常,返回 `{pass, thought, message}`;
                当为 False (默认),失败抛 AssertionError.

        Returns:
            - keep_raw_response=False: True 表示通过,失败则抛 AssertionError
            - keep_raw_response=True:  dict `{pass, thought, message}`

        Raises:
            AssertionError: 仅在 keep_raw_response=False 且断言失败时
        """
        logger.info(f"AI Assert: '{assertion}'")

        # 开始记录任务
        if self.recorder:
            task = self.recorder.start_task("assert", param=assertion)

        # 获取截图（CSS 归一化）
        screenshot_b64, _ = await self._capture_ai_screenshot()

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
            if keep_raw_response:
                return {
                    "pass": False,
                    "thought": "",
                    "message": "Failed to parse assertion response",
                }
            raise error

        passed = bool(response_data.get("pass", False))
        thought = response_data.get("thought", "")

        if passed:
            logger.info(f"Assertion passed: {assertion}")
            if self.recorder:
                self.recorder.finish_task(status="finished", output={"pass": True, "thought": thought})
            if keep_raw_response:
                return {"pass": True, "thought": thought, "message": ""}
            return True

        error_msg = message or f"Assertion failed: {assertion}\nReason: {thought}"
        logger.error(error_msg)
        if self.recorder:
            self.recorder.finish_task(status="failed", error=AssertionError(error_msg))
        if keep_raw_response:
            return {"pass": False, "thought": thought, "message": error_msg}
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
        from ..ai_model.prompts.ui_tars_planning import (
            get_ui_tars_planning_prompt,
        )
        from ..ai_model.ui_tars_planning import parse_ui_tars_planning
        from ..ai_model.auto_glm import (
            get_auto_glm_plan_prompt,
            parse_auto_glm_planning,
            is_auto_glm,
        )
        from ...shared.utils import is_ui_tars as _is_ui_tars_family

        logger.info(f"AI Act: '{task_prompt}'")

        # F4:本次 ai_act 的全部子步骤(Planning / Locate / Tap / ...)都归入一个 execution
        _act_group = None
        if self.session_recorder:
            _act_group = self.session_recorder.start_group(f"ai_act: {task_prompt}")

        # 选择规划语法:UI-TARS / auto-glm 都有各自的 Thought:/Action: 文本语法
        # 或 <think>/<answer> XML 语法,不能与通用 JSON planner 共用 prompt.
        _planner_config = self._get_model_config(INTENT_DEFAULT)
        _use_ui_tars = _is_ui_tars_family(_planner_config.model_family)
        _use_auto_glm = is_auto_glm(_planner_config.model_family)

        # 开始记录步骤
        if self.session_recorder:
            self.session_recorder.start_step("act", task_prompt)

        if self.recorder:
            self.recorder.start_task("act", param=task_prompt)

        # ==================== 缓存读取（与 JS 版本对齐） ====================
        # JS 版本: agent.ts aiAct 中的 cache 逻辑.
        # 对齐 JS `loadYamlFlowAsPlanning` —— 命中后先把"用的是 cached plan"
        # 写进报告,然后逐动作回放并记录 per-action 步骤.
        if use_cache and self.task_cache:
            cache_result = self.task_cache.match_plan_cache(task_prompt)
            if cache_result:
                cached_plan = cache_result.cache_content
                if hasattr(cached_plan, 'yaml_workflow') and cached_plan.yaml_workflow:
                    logger.info(f"Cache hit for ai_act: '{task_prompt}'")
                    # 先把外层 "act" 步骤收尾(标记为 cached planning),随后
                    # _replay_cached_plan 会为每个动作开独立步骤,避免外层
                    # current_step 悬空为 pending.
                    if self.session_recorder and self.session_recorder.current_step:
                        self.session_recorder.complete_step("cached plan loaded")
                    try:
                        success = await self._replay_cached_plan(
                            cached_plan.yaml_workflow
                        )
                        if self.recorder:
                            self.recorder.finish_task(
                                status="finished" if success else "failed"
                            )
                        # F4:cache-hit 分支提前 return,需要在此处收尾 group
                        if self.session_recorder and _act_group:
                            self.session_recorder.end_group(_act_group)
                            _act_group = None
                        return success
                    except Exception as e:
                        logger.warning(
                            f"Cached plan replay failed, falling back to AI: {e}"
                        )
                        # 缓存回放失败,重开一个外层步骤走正常 AI 规划流程
                        if self.session_recorder:
                            self.session_recorder.start_step("act", task_prompt)

        # ==================== 正常 AI 规划流程 ====================
        max_replan_cycles = 10  # 对应 JS: replanningCycleLimit
        replan_count = 0
        conversation_history: List[str] = []
        all_executed_actions: List[Dict[str, Any]] = []  # 收集所有执行的动作，用于缓存

        try:
            while True:
                # 1. 截图 + 获取页面信息（CSS 归一化）
                screenshot_b64, size = await self._capture_ai_screenshot()

                if self.session_recorder:
                    self.session_recorder.record_screenshot_before(screenshot_b64)

                # 2. 调用 AI 规划 —— UI-TARS / auto-glm 走各自的专用 prompt/parser
                history_suffix = (
                    "\n\nHistory:\n" + "\n".join(conversation_history)
                    if conversation_history else ""
                )
                if _use_ui_tars:
                    messages = self._build_messages(
                        system_prompt=get_ui_tars_planning_prompt() + task_prompt + history_suffix,
                        user_prompt="",
                        screenshot_b64=screenshot_b64,
                    )
                elif _use_auto_glm:
                    messages = self._build_messages(
                        system_prompt=get_auto_glm_plan_prompt(
                            _planner_config.model_family
                        ),
                        user_prompt=task_prompt + history_suffix,
                        screenshot_b64=screenshot_b64,
                    )
                else:
                    messages = self._build_messages(
                        system_prompt=system_prompt_to_plan(),
                        user_prompt=plan_task_prompt(
                            task_prompt, conversation_history or None
                        ),
                        screenshot_b64=screenshot_b64,
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
                    _usage = result['usage']
                    self.session_recorder.record_ai_info(
                        model=config.model_name,
                        tokens=_usage.get('total_tokens'),
                        prompt_tokens=_usage.get('prompt_tokens'),
                        completion_tokens=_usage.get('completion_tokens'),
                        response=result.get('content', '')[:2000],
                    )

                # 3. 解析规划结果
                try:
                    if _use_ui_tars:
                        plan_result = parse_ui_tars_planning(
                            result["content"], size
                        )
                    elif _use_auto_glm:
                        plan_result = parse_auto_glm_planning(
                            result["content"], size
                        )
                    else:
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
                    # H4:连续两次空计划 → 视为规划失败,**不**静默返回 True.
                    # JS 等价路径会抛 TaskExecutionError;Python 这里抛 RuntimeError.
                    if replan_count >= 2:
                        raise RuntimeError(
                            f"AI planning produced empty action plan for "
                            f"'{task_prompt}' after {replan_count + 1} attempts — "
                            f"model may be refusing the task or the prompt is "
                            f"under-specified."
                        )
                    replan_count += 1
                    continue

                # 4. 执行每个规划的动作
                for action in actions:
                    action_type = action.get("type", "")
                    param = action.get("param", {})
                    thought = action.get("thought", "")

                    logger.info(f"Executing action: {action_type} - {thought}")

                    success = await self._execute_planned_action(
                        action_type, param
                    )

                    # 先执行,再把结果追加到对话历史和缓存列表 —— 失败不入缓存,
                    # 避免下轮 replan 基于"已执行(实际失败)"的错觉做规划,也避免
                    # 把失败的动作固化到 cache.yaml.
                    if success:
                        conversation_history.append(
                            f"Executed: {action_type} ({thought})"
                        )
                        all_executed_actions.append(action)
                    else:
                        logger.warning(
                            f"Action failed: {action_type} with param {param}"
                        )
                        conversation_history.append(
                            f"Action failed: {action_type} ({thought}) - will retry on next replan"
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
                screenshot_after = await self._capture_recording_screenshot()
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
        finally:
            # F4:无论成功/失败/异常都要收尾分组
            if self.session_recorder and _act_group:
                self.session_recorder.end_group(_act_group)

    # 别名，与 JS 版本的 aiAction 对齐
    ai_action = ai_act

    # ---------------------------------------------------------------
    # H9: JS agent 公开的附加动作 API —— Python 端补齐(别名 + 特化)
    # ---------------------------------------------------------------

    async def ai_tap(self, prompt: str, enable_scroll_retry: bool = True) -> bool:
        """Alias of :meth:`ai_click` — matches JS ``aiTap``."""
        return await self.ai_click(prompt, enable_scroll_retry=enable_scroll_retry)

    async def ai_hover(self, prompt: str, enable_scroll_retry: bool = True) -> bool:
        """Locate by prompt and hover over the element (JS ``aiHover``)."""
        if self.session_recorder:
            self.session_recorder.start_step("hover", prompt)
        if enable_scroll_retry:
            element = await self.ai_locate_with_scroll_retry(prompt)
        else:
            element = await self.ai_locate(prompt)
        if not element:
            if self.session_recorder:
                self.session_recorder.fail_step(f"Cannot locate: {prompt}")
            return False
        await self.interface.hover(element.center[0], element.center[1])
        if self.session_recorder:
            self.session_recorder.complete_step("success")
        return True

    async def ai_right_click(
        self, prompt: str, enable_scroll_retry: bool = True
    ) -> bool:
        """Right-click an element (JS ``aiRightClick``)."""
        if self.session_recorder:
            self.session_recorder.start_step("rightClick", prompt)
        if enable_scroll_retry:
            element = await self.ai_locate_with_scroll_retry(prompt)
        else:
            element = await self.ai_locate(prompt)
        if not element:
            if self.session_recorder:
                self.session_recorder.fail_step(f"Cannot locate: {prompt}")
            return False
        if hasattr(self.interface, "right_click"):
            await self.interface.right_click(element.center[0], element.center[1])
        else:
            logger.warning("interface has no right_click; falling back to click")
            await self.interface.click(element.center[0], element.center[1])
        if self.session_recorder:
            self.session_recorder.complete_step("success")
        return True

    async def ai_double_click(
        self, prompt: str, enable_scroll_retry: bool = True
    ) -> bool:
        """Double-click an element (JS ``aiDoubleClick``)."""
        if self.session_recorder:
            self.session_recorder.start_step("doubleClick", prompt)
        if enable_scroll_retry:
            element = await self.ai_locate_with_scroll_retry(prompt)
        else:
            element = await self.ai_locate(prompt)
        if not element:
            if self.session_recorder:
                self.session_recorder.fail_step(f"Cannot locate: {prompt}")
            return False
        if hasattr(self.interface, "double_click"):
            await self.interface.double_click(element.center[0], element.center[1])
        else:
            # 兜底:两次快速 click
            await self.interface.click(element.center[0], element.center[1])
            await asyncio.sleep(0.05)
            await self.interface.click(element.center[0], element.center[1])
        if self.session_recorder:
            self.session_recorder.complete_step("success")
        return True

    async def ai_keyboard_press(self, key: str) -> bool:
        """
        Press a keyboard key/chord globally (JS ``aiKeyboardPress``).

        Accepts Playwright chord syntax: ``Enter``, ``Escape``, ``Control+a``,
        ``Meta+Shift+P`` etc.
        """
        if self.session_recorder:
            self.session_recorder.start_step("keyboardPress", key)
        try:
            await self.interface.key_press(key)
            if self.session_recorder:
                self.session_recorder.complete_step("success")
            return True
        except Exception as exc:
            logger.error(f"ai_keyboard_press failed: {exc}")
            if self.session_recorder:
                self.session_recorder.fail_step(str(exc))
            return False

    async def ai_boolean(
        self,
        question: str,
    ) -> bool:
        """
        Ask the model a yes/no question about the current page (JS ``aiBoolean``).

        Thin wrapper over :meth:`ai_query` that constrains the output to a
        single boolean field and returns the Python ``bool`` directly.
        """
        parsed = await self.ai_query({
            "value": f"boolean — answer the question: {question}",
        })
        val = parsed.get("data", {}).get("value") if isinstance(parsed, dict) else None
        if isinstance(val, bool):
            return val
        if isinstance(val, str):
            return val.strip().lower() in ("true", "yes", "1", "是", "对")
        return bool(val)

    async def ai_number(self, question: str) -> Optional[float]:
        """Ask for a numeric answer (JS ``aiNumber``). Returns float or None."""
        parsed = await self.ai_query({
            "value": f"number — answer as a numeric value: {question}",
        })
        val = parsed.get("data", {}).get("value") if isinstance(parsed, dict) else None
        if isinstance(val, (int, float)):
            return float(val)
        if isinstance(val, str):
            try:
                return float(val.strip())
            except ValueError:
                return None
        return None

    async def ai_string(self, question: str) -> Optional[str]:
        """Ask for a string answer (JS ``aiString``). Returns str or None."""
        parsed = await self.ai_query({
            "value": f"string — answer as a string: {question}",
        })
        val = parsed.get("data", {}).get("value") if isinstance(parsed, dict) else None
        if val is None:
            return None
        return str(val)

    async def ai_ask(self, question: str) -> str:
        """
        Free-form Q&A about the page (JS ``aiAsk``).

        Unlike ``ai_query`` which enforces a JSON schema, ``ai_ask`` returns the
        model's raw natural-language answer as a string.
        """
        if self.session_recorder:
            self.session_recorder.start_step("ask", question)
        screenshot_b64, _ = await self._capture_ai_screenshot()
        if self.session_recorder:
            self.session_recorder.record_screenshot_before(screenshot_b64)

        system_prompt = (
            "You are a page-analysis assistant. Look at the screenshot and "
            "answer the user's question in natural language. Be concise and "
            "only answer what was asked. Do NOT wrap the answer in JSON, "
            "markdown, or code blocks."
        )
        messages = self._build_messages(
            system_prompt=system_prompt,
            user_prompt=question,
            screenshot_b64=screenshot_b64,
        )

        start_t = time.time()
        config = self._get_model_config(INTENT_DEFAULT)
        result = self._call_ai_with_config(messages, INTENT_DEFAULT)
        elapsed_ms = (time.time() - start_t) * 1000
        logger.info(f"ai_ask completed: {elapsed_ms:.0f}ms")

        answer = (result.get("content") or "").strip()

        if self.session_recorder:
            if result.get("usage"):
                _u = result["usage"]
                self.session_recorder.record_ai_info(
                    model=config.model_name,
                    tokens=_u.get("total_tokens"),
                    prompt_tokens=_u.get("prompt_tokens"),
                    completion_tokens=_u.get("completion_tokens"),
                    response=answer[:2000],
                )
            try:
                shot_after = await self._capture_recording_screenshot()
                self.session_recorder.record_screenshot_after(shot_after)
            except Exception:
                pass
            self.session_recorder.complete_step("success")

        return answer

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
        回放缓存的动作序列(跳过 AI 调用).

        对应 JS agent.ts 的 `loadYamlFlowAsPlanning` + `runYaml`:
        JS 在回放前会把 yaml 计划以独立任务写入 executionDump,使报告里能看见
        "这次跑的是 cached plan + 每个动作的执行结果".为保证日志/报告
        完整性,Python 这里也在每个回放动作上写一条 session_recorder 步骤
        (含前后截图与元数据),而不是静默执行.

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

                step_label = (
                    f"[cached {i + 1}/{len(actions)}] {action_type}"
                    + (f" - {thought}" if thought else "")
                )
                logger.info(f"Replay action: {step_label}")

                # 写入报告:per-action 步骤 + 前后截图
                recorded = False
                if self.session_recorder:
                    try:
                        self.session_recorder.start_step(
                            action_type.lower() or "replay",
                            step_label,
                        )
                        shot_before = await self._capture_recording_screenshot()
                        self.session_recorder.record_screenshot_before(shot_before)
                        recorded = True
                    except Exception as exc:
                        logger.debug(f"Session record start failed: {exc}")
                        recorded = False

                success = await self._execute_planned_action(action_type, param)

                if self.session_recorder and recorded:
                    try:
                        shot_after = await self._capture_recording_screenshot()
                        self.session_recorder.record_screenshot_after(shot_after)
                        if success:
                            self.session_recorder.complete_step("success (cached)")
                        else:
                            self.session_recorder.fail_step(
                                f"cached {action_type} failed"
                            )
                    except Exception as exc:
                        logger.debug(f"Session record finish failed: {exc}")

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

            # 有些规划器(UI-TARS)已经把坐标算好放在 locate.center 里;
            # 这种情况下跳过再次 ai_locate 调用,直接用模型给的坐标点击。
            def _extract_center(p: Dict[str, Any]) -> Optional[Tuple[float, float]]:
                loc = p.get("locate")
                if isinstance(loc, dict):
                    center = loc.get("center")
                    if (
                        isinstance(center, (list, tuple))
                        and len(center) >= 2
                    ):
                        try:
                            return float(center[0]), float(center[1])
                        except (TypeError, ValueError):
                            return None
                return None

            def _extract_prompt(p: Dict[str, Any]) -> str:
                # locate 既可能是字符串也可能是 {prompt: ..., bbox, center}
                loc = p.get("locate")
                if isinstance(loc, str) and loc:
                    return loc
                if isinstance(loc, dict):
                    return str(loc.get("prompt", "") or "")
                return str(p.get("prompt", "") or "")

            if action_upper in ("Tap", "tap", "Click", "click"):
                center = _extract_center(param)
                if center is not None:
                    await self.interface.click(center[0], center[1])
                    return True
                prompt = _extract_prompt(param)
                if not prompt:
                    logger.warning("Tap action missing prompt/locate param")
                    return False
                return await self.ai_click(prompt)

            elif action_upper in ("DoubleClick", "doubleClick", "Double", "LeftDouble"):
                center = _extract_center(param)
                if center is not None and hasattr(self.interface, "double_click"):
                    await self.interface.double_click(center[0], center[1])
                    return True
                prompt = _extract_prompt(param)
                if not prompt:
                    return False
                element = await self.ai_locate_with_scroll_retry(prompt)
                if element and hasattr(self.interface, "double_click"):
                    await self.interface.double_click(
                        element.center[0], element.center[1]
                    )
                    return True
                # 兜底:用普通 click 两次
                if element:
                    await self.interface.click(element.center[0], element.center[1])
                    await asyncio.sleep(0.05)
                    await self.interface.click(element.center[0], element.center[1])
                    return True
                return False

            elif action_upper in ("RightClick", "rightClick", "RightSingle"):
                center = _extract_center(param)
                if center is not None and hasattr(self.interface, "right_click"):
                    await self.interface.right_click(center[0], center[1])
                    return True
                prompt = _extract_prompt(param)
                if not prompt:
                    return False
                element = await self.ai_locate_with_scroll_retry(prompt)
                if element and hasattr(self.interface, "right_click"):
                    await self.interface.right_click(
                        element.center[0], element.center[1]
                    )
                    return True
                return False

            elif action_upper in ("DragAndDrop", "dragAndDrop", "Drag"):
                src = param.get("from") or {}
                dst = param.get("to") or {}
                src_center = _extract_center({"locate": src})
                dst_center = _extract_center({"locate": dst})
                if (
                    src_center is not None
                    and dst_center is not None
                    and hasattr(self.interface, "drag_and_drop")
                ):
                    await self.interface.drag_and_drop(
                        src_center[0], src_center[1],
                        dst_center[0], dst_center[1],
                    )
                    return True
                logger.warning("DragAndDrop missing coordinates, skipped")
                return False

            elif action_upper in ("Input", "input", "Type", "type"):
                center = _extract_center(param)
                value = param.get("value", param.get("text", ""))
                if not value:
                    logger.warning("Input action missing value")
                    return False
                if center is not None:
                    await self.interface.input_text(
                        value, center[0], center[1], clear_first=True
                    )
                    return True
                prompt = _extract_prompt(param)
                if not prompt:
                    # UI-TARS 的 type 可能没有 locate(直接对焦点元素输入),
                    # 回落到不带坐标的输入(依赖当前焦点)
                    await self.interface.input_text(value, clear_first=False)
                    return True
                return await self.ai_input(prompt, value)

            elif action_upper in ("Hover", "hover"):
                center = _extract_center(param)
                if center is not None:
                    await self.interface.hover(center[0], center[1])
                    return True
                prompt = _extract_prompt(param)
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
                # 兼容 JS 老版别名:once/untilBottom/untilTop/untilLeft/untilRight
                scroll_type_raw = param.get("scrollType", "singleAction")
                _scroll_alias = {
                    "once": "singleAction",
                    "untilBottom": "scrollToBottom",
                    "untilTop": "scrollToTop",
                    "untilLeft": "singleAction",
                    "untilRight": "singleAction",
                }
                scroll_type = _scroll_alias.get(scroll_type_raw, scroll_type_raw)

                if scroll_type == "scrollToBottom":
                    for _ in range(20):
                        await self.interface.scroll("down", 800)
                        await asyncio.sleep(0.3)
                elif scroll_type == "scrollToTop":
                    await self.interface.evaluate_javascript(
                        "window.scrollTo(0, 0)"
                    )
                    await asyncio.sleep(0.3)
                else:
                    await self.interface.scroll(direction, distance)
                    await asyncio.sleep(0.5)
                return True

            elif action_upper in (
                "KeyboardPress", "keyboardPress", "KeyPress", "keyPress", "Hotkey", "hotkey"
            ):
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

            elif action_upper in ("Finished", "finished"):
                # UI-TARS / auto-glm 的显式完成信号 —— ai_act 外层 should_continue=False
                logger.info(f"Planner finished: {param.get('content', '')}")
                return True

            elif action_upper in ("EvaluateJavaScript", "evaluateJavaScript"):
                # auto-glm Back → window.history.back() 的落地通道
                script = param.get("script", "") or ""
                if script:
                    await self.interface.evaluate_javascript(script)
                    await asyncio.sleep(0.3)
                    return True
                return False

            else:
                logger.warning(f"Unknown action type: {action_type}")
                return False

        except Exception as e:
            logger.error(f"Error executing action {action_type}: {e}")
            return False

    async def ai_wait_for(
        self,
        assertion: str,
        timeout_ms: Optional[int] = None,
        check_interval_ms: Optional[int] = None,
        *,
        # 兼容旧签名(秒)
        timeout: Optional[float] = None,
        interval: Optional[float] = None,
    ) -> bool:
        """
        等待页面满足某个条件(轮询断言).

        对齐 JS `aiWaitFor` (agent.ts:1250-1261):
        - 默认 `timeout_ms=15000` / `check_interval_ms=3000`(JS 默认)
        - `check_interval_ms` 不能大于 `timeout_ms`,否则立即超时
        - 只有**断言为假**才算"还没达成",才重试;**传输层错误**(网络、模型挂、
          取消)直接抛,不被静默当"条件没过"循环.

        兼容旧签名:允许 `timeout=` / `interval=`(秒)作为 kwarg,自动换算.

        Raises:
            TimeoutError: 条件在 timeout_ms 内未达成
            任何来自底层 AI 调用的非 AssertionError 异常(透传)
        """
        # 归一化参数 (毫秒优先,秒作兼容回退)
        if timeout_ms is None:
            timeout_ms = int((timeout or 15.0) * 1000) if timeout is not None else 15000
        if check_interval_ms is None:
            check_interval_ms = (
                int((interval or 3.0) * 1000) if interval is not None else 3000
            )

        if check_interval_ms > timeout_ms:
            raise ValueError(
                f"check_interval_ms ({check_interval_ms}) must be <= "
                f"timeout_ms ({timeout_ms})"
            )

        logger.info(
            f"AI WaitFor: '{assertion}' "
            f"(timeout_ms={timeout_ms}, check_interval_ms={check_interval_ms})"
        )

        if self.session_recorder:
            self.session_recorder.start_step("waitFor", assertion)

        start = time.time()
        deadline = start + timeout_ms / 1000
        interval_sec = check_interval_ms / 1000
        last_thought = ""

        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                break

            try:
                # keep_raw_response:断言失败不抛 —— 只有 AI 调用真正出错才抛
                result = await self.ai_assert(assertion, keep_raw_response=True)
            except AssertionError:
                # 理论上 keep_raw_response=True 不会抛 AssertionError,但保底
                await asyncio.sleep(min(interval_sec, max(remaining, 0)))
                continue
            # 其他异常(httpx ConnectError / TimeoutError / CancelledError /
            # RuntimeError from AI call):不吞,直接透传给调用方
            if isinstance(result, dict) and result.get("pass"):
                logger.info(f"WaitFor condition met: '{assertion}'")
                if self.session_recorder:
                    self.session_recorder.complete_step("success")
                return True
            if isinstance(result, dict):
                last_thought = result.get("thought") or last_thought

            # 条件未达成 —— 等 interval 或剩余时间(取较小者)后重试
            await asyncio.sleep(min(interval_sec, max(remaining, 0)))

        error_msg = (
            f"WaitFor timeout ({timeout_ms}ms): {assertion}. "
            f"Last thought: {last_thought or 'n/a'}"
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
                screenshot_after = await self._capture_recording_screenshot()
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
