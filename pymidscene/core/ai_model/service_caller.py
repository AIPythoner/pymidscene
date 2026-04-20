"""
AI 模型服务调用器 - 对应 packages/core/src/ai-model/service-caller/index.ts

统一的 AI 模型调用入口，支持多种模型（OpenAI、千问等）。
"""

from __future__ import annotations

import importlib
import json
import os
import re
import time
from collections.abc import Callable
from typing import Any, cast

from openai import OpenAI
from openai.types.chat import ChatCompletion, ChatCompletionMessageParam

from ...shared.logger import logger
from ...shared.utils import (
    extract_json_from_code_block,
    is_ui_tars,
    normalize_json_object,
    preprocess_doubao_bbox_json,
)
from ..types import AIUsageInfo


def _resolve_deep_think(
    deep_think: bool | None,
) -> bool | None:
    """
    Resolve the effective deepThink flag, honoring MIDSCENE_FORCE_DEEP_THINK.

    Aligned with JS `resolveDeepThinkConfig` (service-caller/index.ts:537-598).
    - Env var `MIDSCENE_FORCE_DEEP_THINK=1/true` forces-enable regardless of caller arg.
    - Otherwise the caller-supplied bool wins; `None` means "don't touch".
    """
    force_raw = os.environ.get("MIDSCENE_FORCE_DEEP_THINK", "").strip().lower()
    if force_raw in ("1", "true", "yes", "on"):
        return True
    return deep_think


def _apply_deep_think_params(
    request_params: dict[str, Any],
    model_family: str | None,
    deep_think: bool | None,
) -> None:
    """
    Map deepThink into per-family provider parameters.

    Mirrors JS `resolveDeepThinkConfig` from service-caller/index.ts:537-598:
    - qwen3-vl:       extra_body.config.enable_thinking = bool
    - doubao-vision:  extra_body.thinking.type = "enabled" | "disabled"
    - glm-v:          extra_body.thinking.type = "enabled" | "disabled"
    - gpt-5:          reasoning.effort = "high" | "low"

    Mutates `request_params` in place. No-op if deep_think is None or the family
    has no mapping.
    """
    if deep_think is None or not model_family:
        return

    family = model_family.strip().lower()
    extra_body = cast(dict[str, Any], request_params.setdefault("extra_body", {}))

    if family == "qwen3-vl":
        config_block = cast(dict[str, Any], extra_body.setdefault("config", {}))
        config_block["enable_thinking"] = bool(deep_think)
    elif family in ("doubao-vision", "glm-v"):
        thinking_block = cast(dict[str, Any], extra_body.setdefault("thinking", {}))
        thinking_block["type"] = "enabled" if deep_think else "disabled"
    elif family == "gpt-5":
        reasoning_block = cast(
            dict[str, Any], request_params.setdefault("reasoning", {})
        )
        reasoning_block["effort"] = "high" if deep_think else "low"


def _apply_family_specific_params(
    request_params: dict[str, Any],
    model_family: str | None,
) -> None:
    """
    Per-family request-body tweaks that are NOT deepThink-driven.

    Mirrors JS service-caller/index.ts:271-274 for auto-glm:
    - top_p = 0.85
    - frequency_penalty = 0.2
    """
    if not model_family:
        return
    if model_family in ("auto-glm", "auto-glm-multilingual"):
        request_params.setdefault("top_p", 0.85)
        request_params.setdefault("frequency_penalty", 0.2)


# JSON 修复函数（使用 json-repair 库）
def repair_json(json_str: str) -> str:
    """
    修复不规范的 JSON 字符串

    Args:
        json_str: 需要修复的 JSON 字符串

    Returns:
        修复后的 JSON 字符串
    """
    try:
        module = importlib.import_module("json_repair")
        _repair = cast(Callable[[str], Any], module.repair_json)
        repaired = _repair(json_str)
        if isinstance(repaired, str):
            return repaired
        return json.dumps(repaired)
    except ImportError:
        logger.warning("json-repair not installed, skipping JSON repair")
        return json_str


def safe_parse_json_with_repair(
    text: str,
    model_family: str | None = None,
) -> Any:
    """
    安全解析 JSON，支持自动修复

    对应 JS 版本: safeParseJson (service-caller/index.ts:648-690)

    Args:
        text: JSON 字符串
        model_family: 模型家族（用于特殊处理）

    Returns:
        解析后的对象

    Raises:
        ValueError: 当 JSON 解析失败时
    """
    clean_json_string = extract_json_from_code_block(text)
    last_error: Exception | None = None

    # 匹配点坐标格式 (x,y)
    point_match = re.search(r'\((\d+),(\d+)\)', clean_json_string)
    if point_match:
        return [int(point_match.group(1)), int(point_match.group(2))]

    # 首先尝试直接解析
    try:
        parsed = json.loads(clean_json_string)
        return normalize_json_object(parsed)
    except (json.JSONDecodeError, ValueError) as exc:
        last_error = exc

    # 尝试修复后解析
    try:
        repaired = repair_json(clean_json_string)
        parsed = json.loads(repaired)
        return normalize_json_object(parsed)
    except Exception as exc:
        last_error = exc

    # 豆包/UI-TARS 特殊处理
    if model_family == 'doubao-vision' or is_ui_tars(model_family):
        json_string = preprocess_doubao_bbox_json(clean_json_string)
        try:
            repaired = repair_json(json_string)
            parsed = json.loads(repaired)
            return normalize_json_object(parsed)
        except Exception as exc:
            last_error = exc

    error_message = (
        "failed to parse LLM response into JSON. "
        f"Error - {str(last_error or 'unknown error')}. "
        f"Response - \n {text}"
    )
    logger.error(error_message)
    raise ValueError(error_message) from last_error


class ModelConfig:
    """模型配置"""

    def __init__(
        self,
        model_name: str = "qwen-vl-max",
        base_url: str | None = None,
        api_key: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        timeout: int = 60000,  # 毫秒
        retry_count: int = 1,
        retry_interval: int = 2000,  # 毫秒
        http_proxy: str | None = None,
        socks_proxy: str | None = None,
        model_description: str | None = None,
        model_family: str | None = None,
        intent: str | None = None,
        extra_config: dict[str, Any] | None = None,
        deep_think: bool | None = None,
    ):
        self.model_name = model_name
        self.base_url = base_url
        self.api_key = api_key
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.retry_count = retry_count
        self.retry_interval = retry_interval
        self.http_proxy = http_proxy
        self.socks_proxy = socks_proxy  # H11: SOCKS proxy (独立于 http_proxy)
        self.model_description = model_description or model_name
        self.model_family = model_family
        self.intent = intent
        self.extra_config = extra_config or {}
        # JS `deepThink` 语义:None=不干预;True/False 映射到每家族的推理增强参数.
        # MIDSCENE_FORCE_DEEP_THINK=1 可全局强开.
        self.deep_think = deep_think


def _build_proxied_httpx_client(
    http_proxy: str | None,
    socks_proxy: str | None,
    timeout_sec: float,
) -> Any:
    """
    Build an httpx.Client honoring both HTTP and SOCKS proxies.

    H11: JS ``service-caller/index.ts:83-136`` supports both via
    ``fetch-socks`` / ``socksDispatcher``. Python uses httpx-socks, which is
    an optional dependency — if the user sets ``socks5://...`` but doesn't
    have the package installed we give a clear error rather than silently
    ignoring the proxy.
    """
    import httpx

    if socks_proxy:
        try:
            from httpx_socks import SyncProxyTransport  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "SOCKS proxy support requires the `httpx-socks` package. "
                "Install with: pip install httpx-socks"
            ) from exc
        transport = SyncProxyTransport.from_url(socks_proxy)
        logger.debug(f"Using SOCKS proxy: {socks_proxy}")
        return httpx.Client(transport=transport, timeout=timeout_sec)

    if http_proxy:
        logger.debug(f"Using HTTP proxy: {http_proxy}")
        return httpx.Client(proxies=http_proxy, timeout=timeout_sec)

    return httpx.Client(timeout=timeout_sec)


def create_chat_client(model_config: ModelConfig) -> OpenAI:
    """
    Create an OpenAI-compat SDK client respecting HTTP / SOCKS proxy config
    on ``model_config``.
    """
    client_kwargs: dict[str, Any] = {
        "api_key": model_config.api_key,
        "timeout": model_config.timeout / 1000,  # ms → sec
    }

    if model_config.base_url:
        client_kwargs["base_url"] = model_config.base_url

    # H11: 代理 —— HTTP 或 SOCKS,二选一
    http_proxy = getattr(model_config, "http_proxy", None)
    socks_proxy = getattr(model_config, "socks_proxy", None)
    if http_proxy or socks_proxy:
        client_kwargs["http_client"] = _build_proxied_httpx_client(
            http_proxy=http_proxy,
            socks_proxy=socks_proxy,
            timeout_sec=model_config.timeout / 1000,
        )

    client_kwargs.update(model_config.extra_config)

    return OpenAI(**client_kwargs)


def build_usage_info(
    usage_data: Any,
    time_cost: float,
    model_config: ModelConfig
) -> AIUsageInfo:
    """
    构建 AI 使用信息

    Args:
        usage_data: OpenAI 返回的 usage 数据
        time_cost: 耗时（毫秒）
        model_config: 模型配置

    Returns:
        AIUsageInfo 实例
    """
    return AIUsageInfo(
        prompt_tokens=getattr(usage_data, "prompt_tokens", None),
        completion_tokens=getattr(usage_data, "completion_tokens", None),
        total_tokens=getattr(usage_data, "total_tokens", None),
        cached_input=getattr(
            getattr(usage_data, "prompt_tokens_details", None),
            "cached_tokens",
            None
        ),
        time_cost=time_cost,
        model_name=model_config.model_name,
        model_description=model_config.model_description,
        intent=model_config.intent,
    )


def call_ai(
    messages: list[ChatCompletionMessageParam],
    model_config: ModelConfig,
    stream: bool = False,
    on_chunk: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """
    调用 AI 模型

    Args:
        messages: 消息列表
        model_config: 模型配置
        stream: 是否使用流式输出
        on_chunk: 流式输出回调函数

    Returns:
        包含 content, usage, isStreamed 的字典
    """
    client = create_chat_client(model_config)
    create_completion = cast(Callable[..., Any], client.chat.completions.create)

    start_time = time.time()
    max_attempts = model_config.retry_count + 1
    last_error: Exception | None = None

    # 准备请求参数
    request_params: dict[str, Any] = {
        "model": model_config.model_name,
        "messages": messages,
        "temperature": model_config.temperature,
        "max_tokens": model_config.max_tokens,
    }

    # 千问 VL 特定配置
    is_qwen_vl_model = model_config.model_family == "qwen2.5-vl"
    if not is_qwen_vl_model:
        model_name_lower = model_config.model_name.lower()
        is_qwen_vl_model = "qwen" in model_name_lower and "vl" in model_name_lower

    if is_qwen_vl_model:
        extra_body = cast(
            dict[str, Any], request_params.setdefault("extra_body", {})
        )
        extra_body["vl_high_resolution_images"] = True

    # deepThink → 每家族专用参数(qwen3-vl/doubao/glm-v/gpt-5)
    resolved_deep_think = _resolve_deep_think(model_config.deep_think)
    _apply_deep_think_params(
        request_params, model_config.model_family, resolved_deep_think
    )

    # auto-glm 专用:top_p=0.85, frequency_penalty=0.2
    _apply_family_specific_params(request_params, model_config.model_family)

    logger.info(f"Sending request to {model_config.model_name}")

    # 重试逻辑
    for attempt in range(1, max_attempts + 1):
        try:
            if stream and on_chunk:
                # 流式调用.C10:on_chunk 接受 dict(CodeGenerationChunk 形态),
                # 而非裸 str —— 让消费者能识别增量、最终帧、usage.
                # 为保向后兼容,若 on_chunk 只接受一个位置参数且不是 dict,
                # 仍然可以传 str(见下面的兼容包装).
                accumulated = ""
                accumulated_reasoning = ""
                usage = None

                def _emit(payload: dict[str, Any]) -> None:
                    """
                    Emit a chunk to ``on_chunk``, picking the signature it accepts.

                    New consumers: ``on_chunk(chunk_dict)`` with fields
                    ``content / accumulated / reasoning_content / isComplete / usage``.
                    Legacy consumers: ``on_chunk(str)`` — we pass ``content`` only.
                    """
                    try:
                        on_chunk(payload)  # type: ignore[arg-type]
                    except TypeError:
                        # Fallback for legacy signature `on_chunk(str)`
                        on_chunk(payload.get("content", ""))  # type: ignore[arg-type]

                response_stream = create_completion(
                    **request_params,
                    stream=True
                )

                for chunk in response_stream:
                    if chunk.choices and len(chunk.choices) > 0:
                        delta = chunk.choices[0].delta
                        reasoning_content = getattr(delta, "reasoning_content", None)
                        if delta.content:
                            accumulated += delta.content
                            _emit({
                                "content": delta.content,
                                "accumulated": accumulated,
                                "reasoning_content": reasoning_content or "",
                                "isComplete": False,
                                "usage": None,
                            })

                        if reasoning_content:
                            accumulated_reasoning += reasoning_content

                        if hasattr(chunk, 'usage') and chunk.usage:
                            usage = chunk.usage

                time_cost = (time.time() - start_time) * 1000

                # C10: 合成最终帧 —— 对齐 JS `service-caller/index.ts:336-362`.
                # 若 provider 没给 usage,按 `len(content)/4` 估算 prompt/completion
                # tokens(JS 同样做法),下游 token 统计不会看到 None.
                final_usage_info = None
                if usage is not None:
                    final_usage_info = build_usage_info(
                        usage, time_cost, model_config
                    )
                else:
                    estimated_completion = max(len(accumulated) // 4, 1)
                    # prompt_tokens 估算太不准,留 None,仅给 completion 估算
                    final_usage_info = AIUsageInfo(
                        prompt_tokens=None,
                        completion_tokens=estimated_completion,
                        total_tokens=estimated_completion,
                        cached_input=None,
                        time_cost=time_cost,
                        model_name=model_config.model_name,
                        model_description=model_config.model_description,
                        intent=model_config.intent,
                    )

                _emit({
                    "content": "",
                    "accumulated": accumulated,
                    "reasoning_content": accumulated_reasoning,
                    "isComplete": True,
                    "usage": final_usage_info,
                })

                return {
                    "content": accumulated,
                    "reasoning_content": accumulated_reasoning or None,
                    "usage": final_usage_info,
                    "isStreamed": True,
                }

            else:
                # 非流式调用
                response = cast(ChatCompletion, create_completion(**request_params))

                time_cost = (time.time() - start_time) * 1000

                # 提取响应内容
                if not response.choices:
                    raise ValueError(
                        f"Invalid response from LLM service: {response}"
                    )

                content = response.choices[0].message.content
                if not content:
                    raise ValueError("empty content from AI model")

                reasoning_content = getattr(
                    response.choices[0].message,
                    "reasoning_content",
                    None,
                )

                # 构建使用信息
                usage_info = None
                if response.usage:
                    usage_info = build_usage_info(
                        response.usage,
                        time_cost,
                        model_config
                    )

                logger.info(
                    f"Model response received: "
                    f"model={model_config.model_name}, "
                    f"tokens={response.usage.total_tokens if response.usage else 0}, "
                    f"cost_ms={time_cost:.0f}"
                )

                return {
                    "content": content,
                    "reasoning_content": reasoning_content or None,
                    "usage": usage_info,
                    "isStreamed": False,
                }

        except Exception as e:
            last_error = e
            logger.error(
                f"Attempt {attempt}/{max_attempts} failed: {str(e)}"
            )

            if attempt < max_attempts:
                # 等待后重试
                retry_delay = model_config.retry_interval / 1000
                logger.info(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
            else:
                # 所有重试都失败
                logger.error(f"All {max_attempts} attempts failed")
                raise last_error from e

    # 不应该到达这里，但为了类型检查
    raise RuntimeError("Unexpected error in call_ai")


def extract_json_from_response(content: str) -> Any:
    """
    从 AI 响应中提取 JSON

    Args:
        content: AI 响应内容

    Returns:
        解析后的 JSON 对象
    """
    return safe_parse_json_with_repair(content)


__all__ = [
    "ModelConfig",
    "create_chat_client",
    "call_ai",
    "extract_json_from_response",
    "safe_parse_json_with_repair",
]
