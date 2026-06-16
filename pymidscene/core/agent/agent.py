"""
Agent 核心类 - 对应 packages/core/src/agent/agent.ts

这是 PyMidscene 的核心入口，提供 AI 驱动的自动化能力。
"""

from typing import Optional, Dict, Any, List, Union, Tuple
import inspect
import os
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
    get_configured_max_tokens,
    get_global_model_config_manager,
    INTENT_DEFAULT,
    INTENT_INSIGHT,
    INTENT_PLANNING,
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

    def _resolve_model_family(self, config: ModelConfig) -> str:
        """
        解析坐标适配用的 model_family。

        显式配置优先；未配置时从模型名推断 —— 关键修复 qwen3-vl(归一化
        0-1000 坐标)用户没设 family 标志时被当成 qwen2.5-vl(像素坐标)而
        每次点击错位。

        注意：pymidscene 以 Qwen-VL(qwen2.5 系列, 像素坐标)为主要目标，
        未显式配置 family 且名字也无法识别时默认 qwen2.5-vl。这与 JS 的
        "未配置→normalized-0-1000" 默认有意不同：JS 默认会让最常见的
        qwen-vl-max 路径坐标错位。
        """
        if config.model_family:
            return config.model_family
        name = (config.model_name or "").lower()
        if "qwen3" in name or name.startswith("qwen-vl-3"):
            return "qwen3-vl"
        return "qwen2.5-vl"

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
                # 归一化是 dpr!=1 时的硬性前提: 不归一化, 模型坐标(物理像素)
                # 与点击/标注(CSS 像素)会系统性错位 dpr 倍。静默降级会导致
                # 每次点击都偏 + 报告标注画错位置, 所以这里直接报错(快速失败)。
                raise RuntimeError(
                    f"Screenshot CSS normalization failed on a HiDPI capture "
                    f"(dpr={dpr}); coordinates would be off by {dpr}x. "
                    f"Original error: {exc}"
                ) from exc

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
                            "url": f"data:image/jpeg;base64,{screenshot_b64}",
                            "detail": "high",
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

    async def _call_ai_with_config_async(
        self,
        messages: list[dict[str, Any]],
        intent: str = INTENT_DEFAULT
    ) -> dict[str, Any]:
        """
        在工作线程执行同步 AI 调用, 不阻塞事件循环.

        底层 SDK / httpx 客户端与重试 sleep 都是同步的, 直接在 async 方法里
        调用会把整个 loop 挂住数秒到数十秒(多 Agent / 嵌入 web 服务时致命).
        """
        return await asyncio.to_thread(
            self._call_ai_with_config, messages, intent
        )

    def _native_retry(
        self,
        config: ModelConfig,
        do_call: "Any",
    ) -> dict[str, Any]:
        """
        Run a native-SDK (Gemini/Anthropic) call with JS-style retry.

        对齐 JS service-caller 的非流式重试: 最多 retry_count+1 次, 每次间隔
        retry_interval 毫秒, 任意异常都重试(含 do_call 抛的 'empty content').
        此前两条原生路径完全无重试, config.retry_count/interval 被忽略.
        """
        import time as _t
        attempts = (config.retry_count or 0) + 1
        last_exc: Optional[Exception] = None
        for i in range(1, attempts + 1):
            try:
                return do_call()
            except Exception as e:
                last_exc = e
                logger.error(
                    f"Native AI call attempt {i}/{attempts} failed: {e}"
                )
                if i < attempts:
                    _t.sleep((config.retry_interval or 0) / 1000)
        assert last_exc is not None
        raise last_exc

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

        # Anthropic 的 max_tokens 是必填参数, 不能省略. 用配置值, 未配置时
        # 用一个较大的默认(8192)而非 4096, 避免截断大响应.
        _anthropic_max_tokens = get_configured_max_tokens() or 8192
        # 对齐 JS: 所有 provider 都发 temperature(默认 0), 这是让 VLM 坐标/
        # JSON 输出确定可复现的关键. Anthropic 接受 0-1.
        _temperature = config.temperature if config.temperature is not None else 0

        def _do_call() -> dict[str, Any]:
            response = client.messages.create(
                model=config.model_name,
                max_tokens=_anthropic_max_tokens,
                temperature=_temperature,
                system=system_text if system_text else anthropic.NOT_GIVEN,
                messages=anthropic_messages,
            )

            content_parts: list[str] = []
            for block in getattr(response, "content", []) or []:
                text = getattr(block, "text", None)
                if text:
                    content_parts.append(text)
            content = "".join(content_parts)
            if not content:
                # 对齐 JS: 空响应是硬错误(并被重试), 而不是悄悄返回 ""
                raise RuntimeError("empty content from AI model")

            usage_obj = getattr(response, "usage", None)
            usage: dict[str, Any] | None = None
            if usage_obj is not None:
                prompt_tokens = getattr(usage_obj, "input_tokens", None)
                completion_tokens = getattr(usage_obj, "output_tokens", None)
                total = (prompt_tokens or 0) + (completion_tokens or 0)
                usage = {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": total or None,
                }

            return {"content": content, "usage": usage, "raw_response": response}

        return self._native_retry(config, _do_call)

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
        from google.genai.types import GenerateContentConfig, HttpOptions

        base_url = (config.openai_base_url or "").rstrip("/")
        if not base_url:
            raise ValueError("MIDSCENE_MODEL_BASE_URL is required")

        client = genai.Client(
            api_key=config.openai_api_key,
            http_options=HttpOptions(base_url=base_url),
        )

        # 将 OpenAI 格式的 messages 转换为 Gemini (system_instruction, contents)
        system_text, contents = self._convert_messages_to_gemini_contents(messages)

        logger.info(f"Calling Gemini API via google-genai SDK: model={config.model_name}, base_url={base_url}")

        # 对齐 JS: 发 temperature(默认 0)以让 VLM 输出确定可复现; 系统提示走
        # system_instruction(而非折叠进 user turn); max_output_tokens 仅在配置时设.
        gen_kwargs: dict[str, Any] = {
            "temperature": config.temperature if config.temperature is not None else 0,
        }
        if system_text:
            gen_kwargs["system_instruction"] = system_text
        _max_out = get_configured_max_tokens()
        if _max_out:
            gen_kwargs["max_output_tokens"] = _max_out
        gen_config = GenerateContentConfig(**gen_kwargs)

        def _do_call() -> dict[str, Any]:
            response = client.models.generate_content(
                model=config.model_name,
                contents=contents,
                config=gen_config,
            )

            content = response.text or ""
            if not content:
                raise RuntimeError("empty content from AI model")

            usage = None
            if response.usage_metadata:
                usage = {
                    "prompt_tokens": response.usage_metadata.prompt_token_count,
                    "completion_tokens": response.usage_metadata.candidates_token_count,
                    "total_tokens": response.usage_metadata.total_token_count,
                }

            return {"content": content, "usage": usage, "raw_response": None}

        return self._native_retry(config, _do_call)

    def _convert_messages_to_gemini_contents(
        self,
        messages: List[Dict[str, Any]]
    ) -> tuple[str, list[dict[str, Any]]]:
        """
        将 OpenAI 格式的 messages 转换为 Gemini (system_instruction, contents).

        OpenAI: [{role, content: str | [{type: text/image_url, ...}]}]
        Gemini: system 文本单独走 system_instruction; 其余转 contents
                [{role, parts: [{text} | {inline_data: {mime_type, data}}]}]
        """
        system_parts: list[str] = []
        contents: list[dict[str, Any]] = []
        for msg in messages:
            role = msg.get('role', 'user')
            raw_content = msg.get('content', '')
            if role == 'system':
                # system 文本不折叠进 user turn, 而是收集后走 system_instruction
                if isinstance(raw_content, str):
                    system_parts.append(raw_content)
                elif isinstance(raw_content, list):
                    for item in raw_content:
                        if item.get('type') == 'text':
                            system_parts.append(item.get('text', ''))
                continue
            if role == 'assistant':
                role = 'model'
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
        system_text = "\n\n".join(p for p in system_parts if p)
        return system_text, contents

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
        data: dict[str, Any] = {
            "model": config.model_name,
            "messages": messages,
        }
        # 对齐 JS: 仅在配置了 MIDSCENE_MODEL_MAX_TOKENS / OPENAI_MAX_TOKENS 时
        # 才发送 max_tokens; 否则省略, 由 provider 用其默认(较大)上限, 避免
        # 把大响应硬截断成 4096 → 不完整 JSON → 解析失败.
        _max_tokens = get_configured_max_tokens()
        if _max_tokens is not None:
            data["max_tokens"] = _max_tokens

        # temperature 仅在非零时设置（有些 API 不支持）
        if config.temperature is not None and config.temperature > 0:
            data["temperature"] = config.temperature

        # 应用家族专用 / deepThink 请求参数 —— 此前这些只在 service_caller.call_ai
        # 里生效, 而 live 路径走的是本方法, 导致 qwen2.5-vl 高分辨率、auto-glm
        # 采样参数、deepThink(MIDSCENE_FORCE_DEEP_THINK) 全都没下发。
        # httpx 直发裸 body, 所以把 helper 放进 extra_body 的内容平铺到顶层。
        try:
            from ..ai_model.service_caller import (
                _apply_deep_think_params,
                _apply_family_specific_params,
                _resolve_deep_think,
            )
            family = config.model_family
            if family == "qwen2.5-vl":
                data["vl_high_resolution_images"] = True
            _apply_family_specific_params(data, family)  # auto-glm top_p 等(顶层)
            _dt = _resolve_deep_think(None)  # 读 MIDSCENE_FORCE_DEEP_THINK
            if _dt is not None:
                _apply_deep_think_params(data, family, _dt)
            # helper 把参数放进 data["extra_body"](为 OpenAI SDK 设计); httpx
            # 发裸 body, 这里展平到顶层(等价 SDK 把 extra_body 合进 body)。
            _extra = data.pop("extra_body", None)
            if isinstance(_extra, dict):
                data.update(_extra)
        except Exception as exc:  # pragma: no cover - 不让参数整形阻断调用
            logger.debug(f"family/deep_think param shaping skipped: {exc}")

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

        # 提取响应内容（OpenAI 格式）。部分 OpenAI 兼容端点在过滤/工具调用
        # 场景会返回 content==null —— 规整为 ""(与 Gemini/Anthropic 原生路径
        # 一致, 且避免 None 流到 safe_parse_json 抛 TypeError)。
        try:
            content = result["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            content = None
        if content is None:
            content = ""

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
        # 命中但 XPath 失效时记住匹配项, AI 重定位成功后原地更新该记录
        # (对齐 JS updateOrAppendCacheRecord), 而不是追加新记录让坏记录
        # 永远排在前面、缓存文件跨运行膨胀.
        matched_locate_cache = None
        if use_cache and self.task_cache:
            cache_result = self.task_cache.match_locate_cache(prompt)
            if cache_result:
                matched_locate_cache = cache_result
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
                            # 对齐 JS locator.ts `getElementInfoByXpath`:
                            # 元素可能在视口外 —— 先 scrollIntoView 再取
                            # rect/center。web 的 bounding_box 是视口相对坐标,
                            # 页面已滚动时直接使用会换算错位、点到错误元素。
                            scroll_fn = getattr(
                                self.interface,
                                "scroll_element_by_xpath_into_view",
                                None,
                            )
                            if callable(scroll_fn):
                                try:
                                    await scroll_fn(xpath)
                                    refreshed = (
                                        await self.interface.get_element_by_xpath(
                                            xpath
                                        )
                                    )
                                    if refreshed:
                                        element_info = refreshed
                                except Exception as exc:
                                    logger.debug(
                                        f"Scroll-into-view after cache hit "
                                        f"failed: {exc}"
                                    )
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
        config = self._get_model_config(INTENT_INSIGHT)
        model_family = self._resolve_model_family(config)

        # 准备消息
        messages = self._build_messages(
            system_prompt=system_prompt_to_locate_element(model_family),
            user_prompt=find_element_prompt(prompt),
            screenshot_b64=screenshot_b64
        )

        # 调用 AI
        start_time = time.time()
        result = await self._call_ai_with_config_async(messages, INTENT_INSIGHT)
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
            # 模型按 prompt 约定返回 {"bbox": [], "errors": ["... not found ..."]}
            # 时,把它的"为什么没找到"带出来(对齐 JS service.locate 的 errorLog),
            # 而不是塌成一句通用 "no bbox"。
            errs = response_data.get("errors") if isinstance(response_data, dict) else None
            err_msg = (
                "; ".join(str(e) for e in errs)
                if isinstance(errs, list) and errs
                else "No bbox in response"
            )
            logger.warning(f"AI locate failed: {err_msg}")
            if self.recorder:
                self.recorder.finish_task(status="failed", error=ValueError(err_msg))
            if self.session_recorder:
                self.session_recorder.fail_step(err_msg)
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
        model_family = self._resolve_model_family(config)
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
            # 适配失败按"定位失败"处理. 原始值要么长度不对(format_bbox
            # 直接抛 ValueError 逃出 ai_locate), 要么是 0-1000 归一化坐标
            # 被当像素用 → 必然点错.
            logger.warning(f"Failed to adapt bbox {bbox}: {e}")
            if self.recorder:
                self.recorder.finish_task(status="failed", error=e)
            if self.session_recorder:
                self.session_recorder.fail_step(f"Failed to adapt bbox: {e}")
            return None

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
                    new_record = LocateCache(
                        type="locate",
                        prompt=prompt,
                        cache={"xpaths": xpaths},
                    )
                    if matched_locate_cache is not None:
                        # 命中过但 XPath 失效 → 原地更新旧记录
                        matched_locate_cache.update_fn(new_record)
                    else:
                        self.task_cache.append_cache(new_record)
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
        config = self._get_model_config(INTENT_INSIGHT)
        result = await self._call_ai_with_config_async(messages, INTENT_INSIGHT)
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

        # 准备消息（与 JS tasks.ts:503-516 对齐: 中性布尔判定, 不做任何
        # "屏幕任意位置可见即通过"的放宽 —— 那会造成系统性假阳性,
        # 例如侧边栏菜单里出现"订单"字样就让"当前是订单页"断言通过）
        system_prompt = (
            "You are an AI assistant that verifies UI states based on screenshots.\n"
            "Look at the screenshot carefully and determine whether the following statement is true.\n"
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
            user_prompt=(
                "Boolean, whether the following statement is true: "
                f"{assertion}"
            ),
            screenshot_b64=screenshot_b64
        )

        # 调用 AI
        start_time = time.time()
        config = self._get_model_config(INTENT_INSIGHT)
        result = await self._call_ai_with_config_async(messages, INTENT_INSIGHT)
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

        # 必须是 dict —— 模型可能返回数组/标量(extract_json 现在能提取顶层
        # 数组), 直接 .get 会 AttributeError. 非 dict 一律按解析失败处理。
        if not isinstance(response_data, dict):
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

    @staticmethod
    def _readable_time() -> str:
        """人类可读时间戳(对齐 JS getReadableTimeString,用于 replan 反馈消息)。"""
        from datetime import datetime
        # 带格式后缀(对齐 JS getReadableTimeString 与 prompt 里的示例)。
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S") + " (YYYY-MM-DD HH:mm:ss)"

    @staticmethod
    def _snapshot_history(
        history: List[Dict[str, Any]], max_images: Optional[int] = 2
    ) -> List[Dict[str, Any]]:
        """对话历史快照:只保留最近 ``max_images`` 张截图,更早的降级为占位文本。

        对齐 JS ConversationHistory.snapshot:从最新往旧数,超过上限的 image_url
        替换成 '(image ignored due to size optimization)',控制 token 体积。
        ``max_images=None`` 表示不限制(deepThink)。
        """
        import copy

        cloned = copy.deepcopy(history)
        if max_images is None:
            return cloned
        image_count = 0
        for msg in reversed(cloned):
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            # 外层从新到旧;消息内 content 正向遍历(对齐 JS snapshot,
            # 单条消息含多图时与 JS 保留同一批)。
            for j in range(len(content)):
                part = content[j]
                if isinstance(part, dict) and part.get("type") == "image_url":
                    image_count += 1
                    if image_count > max_images:
                        content[j] = {
                            "type": "text",
                            "text": "(image ignored due to size optimization)",
                        }
        return cloned

    async def _ai_act_xml_loop(
        self,
        task_prompt: str,
        planner_config: "ModelConfig",
        max_replan_cycles: int,
    ) -> List[Dict[str, Any]]:
        """默认规划器:JS XML 单动作契约 + 单动作 replan 循环。

        每轮只规划一个动作,执行后重新截图再规划,直到模型返回 ``complete-task``。
        对话历史是带截图的多轮消息列表(模型上一轮的原始 XML 含 ``<note>``,据此
        把信息带到后续步骤);只保留最近 2 张截图。返回所有成功执行的动作(供缓存)。
        """
        from ..ai_model.prompts.planner import (
            parse_planning_response,
            plan_task_prompt,
            system_prompt_to_plan,
        )

        model_family = planner_config.model_family
        system_prompt = system_prompt_to_plan()
        user_instruction = plan_task_prompt(task_prompt)

        all_executed_actions: List[Dict[str, Any]] = []
        history: List[Dict[str, Any]] = []
        pending_feedback: Optional[str] = None
        replan_count = 0
        action_error_count = 0
        parse_error_count = 0

        while True:
            # 1. 截图(默认规划器基于 prompt 定位,不需要 size 做 bbox 适配)
            screenshot_b64, _size = await self._capture_ai_screenshot()
            if self.session_recorder:
                self.session_recorder.record_screenshot_before(screenshot_b64)

            # 2. 把本轮反馈 + 当前截图追加进历史
            if pending_feedback:
                feedback_text = (
                    f"{pending_feedback}. The last screenshot is attached. "
                    f"Please going on according to the instruction."
                )
                pending_feedback = None
            else:
                feedback_text = "this is the latest screenshot"
            history.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": feedback_text},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{screenshot_b64}",
                            "detail": "high",
                        },
                    },
                ],
            })

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_instruction},
                *self._snapshot_history(history, max_images=2),
            ]

            # 3. 调用模型
            start_time = time.time()
            result = await self._call_ai_with_config_async(
                messages, INTENT_PLANNING
            )
            elapsed_ms = (time.time() - start_time) * 1000
            raw = result.get("content", "") or ""

            # 把模型原始 XML 追加进历史(含 <note>,供后续步骤参考)
            history.append({"role": "assistant", "content": raw})

            if self.recorder and result.get("usage"):
                usage_info = result["usage"].copy()
                usage_info["time_cost"] = elapsed_ms / 1000
                usage_info["model_name"] = planner_config.model_name
                self.recorder.record_ai_usage(usage_info)
            if self.session_recorder and result.get("usage"):
                _u = result["usage"]
                self.session_recorder.record_ai_info(
                    model=planner_config.model_name,
                    tokens=_u.get("total_tokens"),
                    prompt_tokens=_u.get("prompt_tokens"),
                    completion_tokens=_u.get("completion_tokens"),
                    response=raw[:2000],
                )

            # 4. 解析 XML 单动作响应
            try:
                plan = parse_planning_response(raw, model_family)
            except Exception as e:  # noqa: BLE001
                logger.error(f"Failed to parse XML planning response: {e}")
                logger.debug(f"Raw response: {raw[:500]}")
                parse_error_count += 1
                if parse_error_count > 2:
                    raise RuntimeError(
                        f"Failed to parse AI planning response for "
                        f"'{task_prompt}' after {parse_error_count} attempts: {e}"
                    ) from e
                pending_feedback = (
                    f"Time: {self._readable_time()}, your previous response "
                    f"could not be parsed ({e}). Please answer strictly in the "
                    f"required XML format."
                )
                replan_count += 1
                if replan_count > max_replan_cycles:
                    raise RuntimeError(
                        f"Max replan cycles ({max_replan_cycles}) exceeded for "
                        f"task: '{task_prompt}'."
                    ) from e
                continue

            log_msg = plan.get("log")
            if log_msg:
                logger.info(f"Act: {log_msg}")

            # 5. <error> / complete-task success=false → 抛错(对齐 JS tasks.ts)
            error_tag = plan.get("error")
            if error_tag:
                raise RuntimeError(
                    f"Failed to continue: {error_tag}\n{log_msg or ''}"
                )
            if plan.get("finalizeSuccess") is False:
                raise RuntimeError(
                    f"Task failed: "
                    f"{plan.get('finalizeMessage') or 'No error message provided'}"
                    f"\n{log_msg or ''}"
                )

            actions = plan.get("actions", [])
            should_continue = plan.get("shouldContinuePlanning", True)

            # 6. 执行该单动作(0 或 1 个)
            if actions:
                action = actions[0]
                action_type = action.get("type", "")
                param = action.get("param", {})
                thought = action.get("thought", "")
                logger.info(f"Executing action: {action_type} - {thought}")
                success = await self._execute_planned_action(action_type, param)
                if success:
                    all_executed_actions.append(action)
                else:
                    logger.warning(
                        f"Action failed: {action_type} with param {param}"
                    )
                    action_error_count += 1
                    if action_error_count > 5:
                        raise RuntimeError(
                            f"Too many action failures ({action_error_count}) "
                            f"while executing '{task_prompt}'"
                        )
                    pending_feedback = (
                        f"Time: {self._readable_time()}, error executing the "
                        f"previous action ({action_type}). Please try to recover."
                    )

            # 7. 终止:仅 complete-task(success=true)结束;否则继续 replan
            if not should_continue:
                logger.info(f"AI Act completed: '{task_prompt}'")
                break

            replan_count += 1
            if replan_count > max_replan_cycles:
                raise RuntimeError(
                    f"Max replan cycles ({max_replan_cycles}) exceeded for task: "
                    f"'{task_prompt}' — task is incomplete. Raise "
                    f"MIDSCENE_REPLANNING_CYCLE_LIMIT if the task legitimately "
                    f"needs more steps."
                )

            if not pending_feedback:
                pending_feedback = (
                    f"Time: {self._readable_time()}, I have finished the action "
                    f"previously planned."
                )
            await asyncio.sleep(0.5)

        return all_executed_actions

    async def _ai_act_legacy_loop(
        self,
        task_prompt: str,
        use_ui_tars: bool,
        use_auto_glm: bool,
        planner_config: "ModelConfig",
        max_replan_cycles: int,
    ) -> List[Dict[str, Any]]:
        """UI-TARS / auto-glm 规划器:沿用原批量循环(各自的 Thought:/Action: 语法)。

        这两类模型每次也是一步一动作,但用自己的文本/XML 语法和截图绝对坐标,
        与默认 XML 契约不同,故保留独立循环。返回所有成功执行的动作。
        """
        from ..ai_model.auto_glm import (
            get_auto_glm_plan_prompt,
            parse_auto_glm_planning,
        )
        from ..ai_model.prompts.ui_tars_planning import (
            get_ui_tars_planning_prompt,
        )
        from ..ai_model.ui_tars_planning import parse_ui_tars_planning

        replan_count = 0
        action_error_count = 0
        conversation_history: List[str] = []
        all_executed_actions: List[Dict[str, Any]] = []

        while True:
            screenshot_b64, size = await self._capture_ai_screenshot()
            if self.session_recorder:
                self.session_recorder.record_screenshot_before(screenshot_b64)

            history_suffix = (
                "\n\nHistory:\n" + "\n".join(conversation_history)
                if conversation_history else ""
            )
            if use_ui_tars:
                messages = self._build_messages(
                    system_prompt=get_ui_tars_planning_prompt()
                    + task_prompt + history_suffix,
                    user_prompt="",
                    screenshot_b64=screenshot_b64,
                )
            else:
                messages = self._build_messages(
                    system_prompt=get_auto_glm_plan_prompt(
                        planner_config.model_family
                    ),
                    user_prompt=task_prompt + history_suffix,
                    screenshot_b64=screenshot_b64,
                )

            start_time = time.time()
            config = self._get_model_config(INTENT_PLANNING)
            result = await self._call_ai_with_config_async(
                messages, INTENT_PLANNING
            )
            elapsed_ms = (time.time() - start_time) * 1000
            logger.info(
                f"AI planning completed: {elapsed_ms:.0f}ms, "
                f"tokens={result.get('usage', {}).get('total_tokens', 0) if result.get('usage') else 0}"
            )

            if self.recorder and result.get("usage"):
                usage_info = result["usage"].copy()
                usage_info["time_cost"] = elapsed_ms / 1000
                usage_info["model_name"] = config.model_name
                self.recorder.record_ai_usage(usage_info)
            if self.session_recorder and result.get("usage"):
                _usage = result["usage"]
                self.session_recorder.record_ai_info(
                    model=config.model_name,
                    tokens=_usage.get("total_tokens"),
                    prompt_tokens=_usage.get("prompt_tokens"),
                    completion_tokens=_usage.get("completion_tokens"),
                    response=result.get("content", "")[:2000],
                )

            try:
                if use_ui_tars:
                    plan_result = parse_ui_tars_planning(result["content"], size)
                else:
                    plan_result = parse_auto_glm_planning(result["content"], size)
            except Exception as e:  # noqa: BLE001
                logger.error(f"Failed to parse planning response: {e}")
                logger.debug(f"Raw response: {result['content'][:500]}")
                conversation_history.append(f"Planning parse error: {e}")
                if replan_count >= 2:
                    raise RuntimeError(
                        f"Failed to parse AI planning response for "
                        f"'{task_prompt}' after {replan_count + 1} attempts: {e}"
                    ) from e
                replan_count += 1
                continue

            actions = plan_result.get("actions", [])
            should_continue = plan_result.get("shouldContinuePlanning", False)

            if not actions:
                if not should_continue:
                    logger.info(
                        "Planner returned no actions and no further planning "
                        "— treating task as complete"
                    )
                    break
                logger.warning("AI returned empty action plan")
                conversation_history.append("No actions planned")
                if replan_count >= 2:
                    raise RuntimeError(
                        f"AI planning produced empty action plan for "
                        f"'{task_prompt}' after {replan_count + 1} attempts — "
                        f"model may be refusing the task or the prompt is "
                        f"under-specified."
                    )
                replan_count += 1
                continue

            for action in actions:
                action_type = action.get("type", "")
                param = action.get("param", {})
                thought = action.get("thought", "")
                logger.info(f"Executing action: {action_type} - {thought}")
                success = await self._execute_planned_action(action_type, param)
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
                    action_error_count += 1
                    if action_error_count > 5:
                        raise RuntimeError(
                            f"Too many action failures ({action_error_count}) "
                            f"while executing '{task_prompt}'"
                        )
                    should_continue = True
                    break

            if not should_continue:
                logger.info(f"AI Act completed: '{task_prompt}'")
                break

            replan_count += 1
            if replan_count > max_replan_cycles:
                raise RuntimeError(
                    f"Max replan cycles ({max_replan_cycles}) exceeded for task: "
                    f"'{task_prompt}' — task is incomplete. Raise "
                    f"MIDSCENE_REPLANNING_CYCLE_LIMIT if the task legitimately "
                    f"needs more steps."
                )
            logger.info(f"Replanning (cycle {replan_count}/{max_replan_cycles})")
            await asyncio.sleep(0.5)

        return all_executed_actions

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
        from ..ai_model.auto_glm import is_auto_glm
        from ...shared.utils import is_ui_tars as _is_ui_tars_family

        logger.info(f"AI Act: '{task_prompt}'")

        # F4:本次 ai_act 的全部子步骤(Planning / Locate / Tap / ...)都归入一个 execution
        _act_group = None
        if self.session_recorder:
            _act_group = self.session_recorder.start_group(f"ai_act: {task_prompt}")

        # 选择规划语法:UI-TARS / auto-glm 都有各自的 Thought:/Action: 文本语法
        # 或 <think>/<answer> XML 语法,不能与通用 JSON planner 共用 prompt.
        _planner_config = self._get_model_config(INTENT_PLANNING)
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
        # 对齐 JS agent.ts:901-907: UI-TARS / auto-GLM 规划产出的是
        # 截图绝对坐标, 不可跨次回放, 跳过 plan 缓存(读和写).
        _plan_cacheable = not (_use_ui_tars or _use_auto_glm)
        matched_plan_cache = None  # 回放失败时记住匹配项, 新计划原地更新
        if use_cache and self.task_cache and _plan_cacheable:
            cache_result = self.task_cache.match_plan_cache(task_prompt)
            if cache_result:
                matched_plan_cache = cache_result
                cached_plan = cache_result.cache_content
                if hasattr(cached_plan, 'yaml_workflow') and cached_plan.yaml_workflow:
                    logger.info(f"Cache hit for ai_act: '{task_prompt}'")
                    # 先把外层 "act" 步骤收尾(标记为 cached planning),随后
                    # _replay_cached_plan 会为每个动作开独立步骤,避免外层
                    # current_step 悬空为 pending.
                    if self.session_recorder and self.session_recorder.current_step:
                        self.session_recorder.complete_step("cached plan loaded")
                    replay_error: str | None = None
                    try:
                        success = await self._replay_cached_plan(
                            cached_plan.yaml_workflow
                        )
                        if success:
                            if self.recorder:
                                self.recorder.finish_task(status="finished")
                            # F4:cache-hit 分支提前 return,需要在此处收尾 group
                            if self.session_recorder and _act_group:
                                self.session_recorder.end_group(_act_group)
                                _act_group = None
                            return True
                        replay_error = "replay reported failure"
                    except Exception as e:
                        replay_error = str(e)
                    # 回放失败(解析不了 / 某动作失败)一律回退 AI 规划,
                    # 而不是把整个 ai_act 判为失败 —— 对齐 JS:缓存只是加速,
                    # 不能因为一条(可能来自旧版/JS 版的)缓存让任务直接挂掉.
                    logger.warning(
                        f"Cached plan replay failed, falling back to AI: "
                        f"{replay_error}"
                    )
                    if self.session_recorder:
                        self.session_recorder.start_step("act", task_prompt)

        # ==================== 正常 AI 规划流程 ====================
        # 对齐 JS agent.ts:145-147 + MIDSCENE_REPLANNING_CYCLE_LIMIT 环境变量:
        # 默认 20, UI-TARS 40(单步一动作), auto-GLM 100.
        _limit_env = os.environ.get("MIDSCENE_REPLANNING_CYCLE_LIMIT")
        if _limit_env:
            max_replan_cycles = int(_limit_env)
        elif _use_auto_glm:
            max_replan_cycles = 100
        elif _use_ui_tars:
            max_replan_cycles = 40
        else:
            max_replan_cycles = 20
        all_executed_actions: List[Dict[str, Any]] = []

        try:
            # 规划循环:默认走 XML 单动作契约;UI-TARS / auto-glm 走各自的循环。
            if _use_ui_tars or _use_auto_glm:
                all_executed_actions = await self._ai_act_legacy_loop(
                    task_prompt, _use_ui_tars, _use_auto_glm,
                    _planner_config, max_replan_cycles,
                )
            else:
                all_executed_actions = await self._ai_act_xml_loop(
                    task_prompt, _planner_config, max_replan_cycles,
                )

            # ==================== 缓存写入（与 JS 版本对齐） ====================
            if (
                use_cache
                and self.task_cache
                and _plan_cacheable
                and all_executed_actions
            ):
                yaml_workflow = self._actions_to_yaml_workflow(
                    all_executed_actions, task_prompt
                )
                new_plan_record = PlanningCache(
                    type="plan",
                    prompt=task_prompt,
                    yaml_workflow=yaml_workflow
                )
                if matched_plan_cache is not None:
                    # 命中过但回放失败 → 原地更新旧记录
                    # (对齐 JS updateOrAppendCacheRecord)
                    matched_plan_cache.update_fn(new_plan_record)
                else:
                    self.task_cache.append_cache(new_plan_record)
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
        # demand 用 `result` 键 + 首字母大写类型前缀(对齐 JS createTypeQueryTask
        # `{result: "Boolean, <q>"}`,也与 extractor 系统 prompt 里的示例一致 ——
        # 之前用 `value` 键会和 prompt 示例自相矛盾,模型回 `result` 时取不到值)。
        parsed = await self.ai_query({"result": f"Boolean, {question}"})
        val = parsed.get("data", {}).get("result") if isinstance(parsed, dict) else None
        if isinstance(val, bool):
            return val
        if isinstance(val, str):
            return val.strip().lower() in ("true", "yes", "1", "是", "对")
        return bool(val)

    async def ai_number(self, question: str) -> Optional[float]:
        """Ask for a numeric answer (JS ``aiNumber``). Returns float or None."""
        parsed = await self.ai_query({"result": f"Number, {question}"})
        val = parsed.get("data", {}).get("result") if isinstance(parsed, dict) else None
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
        parsed = await self.ai_query({"result": f"String, {question}"})
        val = parsed.get("data", {}).get("result") if isinstance(parsed, dict) else None
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
        config = self._get_model_config(INTENT_INSIGHT)
        result = await self._call_ai_with_config_async(messages, INTENT_INSIGHT)
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

    # 动作类型 ↔ JS yaml flow 键(interfaceAlias)的映射.
    # 对齐 JS device/index.ts 的 actionSpace + common.ts buildYamlFlowFromPlans:
    # flowKey = interfaceAlias || name(Sleep 无 alias, 用原名).
    _FLOW_KEY_BY_ACTION_TYPE = {
        "Tap": "aiTap",
        "RightClick": "aiRightClick",
        "DoubleClick": "aiDoubleClick",
        "Hover": "aiHover",
        "Input": "aiInput",
        "KeyboardPress": "aiKeyboardPress",
        "Scroll": "aiScroll",
        "DragAndDrop": "aiDragAndDrop",
        "Sleep": "Sleep",
        # 默认 XML planner 也会规划这两类,必须能进/出缓存(否则回放缺步骤):
        # LongPress 用 verb 作 flow key(对齐 JS interfaceAlias 缺省回落 verb);
        # Assert 走 aiAssert(condition 作为普通 param 字段往返)。
        "LongPress": "LongPress",
        "Assert": "aiAssert",
    }
    # 读取侧反向映射, 额外接受 yaml 脚本里的小写 `sleep` 内置项.
    _ACTION_TYPE_BY_FLOW_KEY = {
        **{v: k for k, v in _FLOW_KEY_BY_ACTION_TYPE.items()},
        "sleep": "Sleep",
    }
    # 这些 param 字段是 locator(JS MidsceneLocationType), 序列化时只保留 prompt
    _LOCATOR_PARAM_FIELDS = ("locate", "from", "to")

    def _actions_to_yaml_workflow(
        self, actions: List[Dict[str, Any]], task_prompt: str
    ) -> str:
        """
        将动作列表序列化为 JS 兼容的 MidsceneYamlScript 字符串（用于缓存）.

        对齐 JS agent.ts:948-957: `yaml.dump({tasks: [{name, flow}]})`,
        flow 项为 `{<interfaceAlias>: '', ...param}`、locator 字段降为 prompt
        字符串(common.ts `dumpActionParam`). 缓存文件必须能被 JS 版读取.
        """
        import yaml

        flow: list[dict[str, Any]] = []
        for action in actions:
            action_type = action.get("type", "")
            flow_key = self._FLOW_KEY_BY_ACTION_TYPE.get(action_type)
            if flow_key is None:
                logger.warning(
                    f"Cannot convert action {action_type} to yaml flow, ignored"
                )
                continue
            item: dict[str, Any] = {flow_key: ""}
            param = action.get("param") or {}
            if isinstance(param, dict):
                for key, value in param.items():
                    if key in self._LOCATOR_PARAM_FIELDS and isinstance(
                        value, dict
                    ):
                        prompt = value.get("prompt")
                        if isinstance(prompt, dict):
                            prompt = prompt.get("prompt")
                        if prompt:
                            item[key] = prompt
                    else:
                        item[key] = value
            flow.append(item)

        return yaml.dump(
            {"tasks": [{"name": task_prompt, "flow": flow}]},
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )

    def _parse_cached_workflow(
        self, yaml_workflow: str
    ) -> list[dict[str, Any]] | None:
        """
        解析缓存的 yaml workflow, 返回 [{type, param}] 动作列表.

        同时支持两种格式:
        - JS MidsceneYamlScript: `{tasks: [{name, flow: [{aiTap: '', ...}]}]}`
        - 旧版 Python 裸列表: `[{type, param, thought}]`(0.3.1 及之前写入)

        解析失败返回 None(调用方回退 AI 规划, 不能当作任务失败).
        """
        import yaml

        loaded = yaml.safe_load(yaml_workflow)

        if isinstance(loaded, list):  # 旧版 Python 格式
            return [a for a in loaded if isinstance(a, dict) and a.get("type")]

        if isinstance(loaded, dict) and isinstance(loaded.get("tasks"), list):
            actions: list[dict[str, Any]] = []
            for task in loaded["tasks"]:
                for item in (task or {}).get("flow") or []:
                    if not isinstance(item, dict):
                        continue
                    flow_key = next(
                        (
                            k
                            for k in item
                            if k in self._ACTION_TYPE_BY_FLOW_KEY
                        ),
                        None,
                    )
                    if flow_key is None:
                        logger.warning(
                            f"Unsupported cached flow item, ignored: "
                            f"{list(item.keys())}"
                        )
                        continue
                    action_type = self._ACTION_TYPE_BY_FLOW_KEY[flow_key]
                    param = {
                        k: v for k, v in item.items() if k != flow_key
                    }
                    # yaml 脚本简写: `aiTap: 'login button'` / `sleep: 2000`
                    key_value = item[flow_key]
                    if key_value not in ("", None):
                        if action_type == "Sleep":
                            param.setdefault("timeMs", key_value)
                        else:
                            param.setdefault("locate", key_value)
                    actions.append({"type": action_type, "param": param})
            return actions

        logger.warning(
            f"Unrecognized cached workflow shape: {type(loaded).__name__}"
        )
        return None

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
        try:
            actions = self._parse_cached_workflow(yaml_workflow)
            if not actions:
                logger.warning("Cached workflow parsed empty, fallback to AI")
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
            # 模型可能发 "param": null —— `.get("param", {})` 对 null 返回 None,
            # 后续 param.get(...) 会 AttributeError 被 catch-all 吞成失败。
            # 统一规整为 dict, 让各分支走干净的"缺参数"逻辑。
            if not isinstance(param, dict):
                param = {}

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

            elif action_upper in ("LongPress", "longPress", "Long Press"):
                duration = param.get("duration", param.get("durationMs"))
                center = _extract_center(param)
                if center is None:
                    prompt = _extract_prompt(param)
                    if not prompt:
                        return False
                    element = await self.ai_locate_with_scroll_retry(prompt)
                    if not element:
                        return False
                    center = (element.center[0], element.center[1])
                if hasattr(self.interface, "long_press"):
                    if duration:
                        await self.interface.long_press(
                            center[0], center[1], int(duration)
                        )
                    else:
                        # 不传 duration, 让各平台用自己的默认值
                        # (Android 2000ms / iOS 1000ms / web 500ms)
                        await self.interface.long_press(center[0], center[1])
                    return True
                logger.warning("Interface does not support long_press")
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
                value = param.get("value", param.get("text", None))
                # 对齐 JS agent.ts:722-725: 空字符串是合法输入("清空输入框"),
                # 只有完全没给 value 才算参数缺失
                if value is None:
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
                # 对齐 JS `param?.distance || undefined`: 不传则用 interface
                # 默认值(web 视口 70%、Android 整屏、iOS 1/3 屏)
                distance = param.get("distance") or None
                # 兼容 JS 老版别名:once/untilBottom/untilTop/untilLeft/untilRight
                scroll_type_raw = param.get("scrollType") or "singleAction"
                _scroll_alias = {
                    "once": "singleAction",
                    "untilBottom": "scrollToBottom",
                    "untilTop": "scrollToTop",
                    "untilLeft": "scrollToLeft",
                    "untilRight": "scrollToRight",
                }
                scroll_type = _scroll_alias.get(scroll_type_raw, scroll_type_raw)

                # 对齐 JS web-page.ts:488-495: 规划器指定了 locate 时,
                # 元素中心作为滚动起点(可滚动内部容器/指定列表)
                starting_point = _extract_center(param)
                if starting_point is None:
                    prompt = _extract_prompt(param)
                    if prompt:
                        element = await self.ai_locate(prompt)
                        if element:
                            starting_point = (
                                element.center[0],
                                element.center[1],
                            )
                await self._perform_scroll(
                    direction, distance, scroll_type, starting_point
                )
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

            elif action_upper in ("Navigate", "navigate", "OpenUrl", "GoToUrl"):
                url = param.get("url", param.get("uri", "")) or ""
                if not url:
                    logger.warning("Navigate action missing url")
                    return False
                if hasattr(self.interface, "navigate"):
                    await self.interface.navigate(url)
                    return True
                if hasattr(self.interface, "launch"):
                    # Android/iOS: URL 经 launch 通道打开
                    await self.interface.launch(url)
                    return True
                logger.warning("Interface does not support navigation")
                return False

            elif action_upper in ("Reload", "reload", "Refresh", "refresh"):
                if hasattr(self.interface, "reload"):
                    await self.interface.reload()
                    return True
                logger.warning("Interface does not support reload")
                return False

            elif action_upper in (
                "GoBack", "goBack", "Back", "back", "AndroidBackButton"
            ):
                if hasattr(self.interface, "go_back"):
                    await self.interface.go_back()
                    return True
                if hasattr(self.interface, "back"):
                    # AndroidDevice.back() = BACK 键
                    await self.interface.back()
                    return True
                await self.interface.evaluate_javascript("window.history.back()")
                await asyncio.sleep(0.3)
                return True

            elif action_upper in ("Home", "home", "AndroidHomeButton"):
                # Android/iOS have home(); web has no home concept (no-op).
                if hasattr(self.interface, "home"):
                    await self.interface.home()
                    return True
                logger.debug("Interface does not support Home; treating as no-op")
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

            check_start = time.time()
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

            # 条件未达成 —— 对齐 JS tasks.ts:697-710: 间隔扣除本次断言耗时
            # (单次 AI 调用 2-3s 时不再叠加完整 interval, 否则 15s 窗口内的
            # 检查次数明显少于 JS, 更易误报超时); 检查比 interval 还慢则
            # 立即进入下一轮.
            elapsed = time.time() - check_start
            sleep_for = max(0.0, interval_sec - elapsed)
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            await asyncio.sleep(min(sleep_for, remaining))

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
        distance: int | None = None,
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
            starting_point: tuple[float, float] | None = None
            if locate_prompt:
                element = await self.ai_locate(locate_prompt)
                if element:
                    starting_point = (element.center[0], element.center[1])

            await self._perform_scroll(
                direction, distance, scroll_type, starting_point
            )

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

    async def _perform_scroll(
        self,
        direction: str,
        distance: int | None,
        scroll_type: str,
        starting_point: tuple[float, float] | None,
    ) -> None:
        """
        滚动路由（ai_scroll 与规划执行器共用）。

        scrollTo* 优先用 interface 原生的 `scroll_until_*`（Android/iOS 手势、
        Playwright mouse.wheel ±9999999，均支持从定位元素起步）；没有时回退
        `window.scrollTo` 脚本。singleAction 带起点时走 `_scroll_from_point`。
        """
        scroll_until_methods = {
            "scrollToTop": "scroll_until_top",
            "scrollToBottom": "scroll_until_bottom",
            "scrollToLeft": "scroll_until_left",
            "scrollToRight": "scroll_until_right",
        }
        if scroll_type in scroll_until_methods:
            native = getattr(
                self.interface, scroll_until_methods[scroll_type], None
            )
            if callable(native):
                await native(start_point=starting_point)
            else:
                scripts = {
                    "scrollToTop": "window.scrollTo(window.scrollX, 0)",
                    "scrollToBottom": (
                        "window.scrollTo(window.scrollX, "
                        "document.body.scrollHeight)"
                    ),
                    "scrollToLeft": "window.scrollTo(0, window.scrollY)",
                    "scrollToRight": (
                        "window.scrollTo(document.body.scrollWidth, "
                        "window.scrollY)"
                    ),
                }
                await self.interface.evaluate_javascript(scripts[scroll_type])
            await asyncio.sleep(0.3)
        else:
            # singleAction
            if starting_point is not None:
                await self._scroll_from_point(
                    direction, distance, starting_point
                )
            else:
                await self.interface.scroll(direction, distance)
            await asyncio.sleep(0.5)

    async def _scroll_from_point(
        self,
        direction: str,
        distance: int | None,
        starting_point: tuple[float, float],
    ) -> None:
        """
        从指定起点（AI 定位到的元素中心）单次滚动。

        优先用 interface 原生的起点参数（Android/iOS 的 `start_point`、
        Playwright 的 `starting_point`），都没有时回退到
        `elementFromPoint().scrollBy()` 脚本（仅对 web 有效）。
        """
        try:
            params = inspect.signature(self.interface.scroll).parameters
        except (TypeError, ValueError):
            params = {}

        if "start_point" in params:
            await self.interface.scroll(
                direction, distance, start_point=starting_point
            )
            return
        if "starting_point" in params:
            await self.interface.scroll(
                direction,
                distance,
                starting_point={
                    "x": starting_point[0],
                    "y": starting_point[1],
                },
            )
            return

        d = distance if distance is not None else 500
        delta_y = d if direction == "down" else -d if direction == "up" else 0
        delta_x = d if direction == "right" else -d if direction == "left" else 0
        await self.interface.evaluate_javascript(f"""
            (() => {{
                const el = document.elementFromPoint(
                    {starting_point[0]}, {starting_point[1]}
                );
                if (el) {{
                    el.scrollBy({delta_x}, {delta_y});
                }}
            }})()
        """)

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
