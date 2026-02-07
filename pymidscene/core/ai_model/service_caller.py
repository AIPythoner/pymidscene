"""
AI 模型服务调用器 - 对应 packages/core/src/ai-model/service-caller/index.ts

统一的 AI 模型调用入口，支持多种模型（OpenAI、千问等）。
"""

import re
from typing import Optional, Dict, Any, List, Callable
import time
import json
from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam, ChatCompletion

from ...shared.logger import logger
from ...shared.utils import (
    safe_parse_json,
    extract_json_from_code_block,
    normalize_json_object,
    preprocess_doubao_bbox_json,
    is_ui_tars,
)
from ..types import AIUsageInfo


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
        from json_repair import repair_json as _repair
        return _repair(json_str)
    except ImportError:
        logger.warning("json-repair not installed, skipping JSON repair")
        return json_str


def safe_parse_json_with_repair(
    text: str,
    model_family: Optional[str] = None
) -> Optional[Any]:
    """
    安全解析 JSON，支持自动修复
    
    对应 JS 版本: safeParseJson (service-caller/index.ts:648-690)

    Args:
        text: JSON 字符串
        model_family: 模型家族（用于特殊处理）

    Returns:
        解析后的对象，失败返回 None
    """
    clean_json_string = extract_json_from_code_block(text)
    
    # 匹配点坐标格式 (x,y)
    point_match = re.match(r'\((\d+),(\d+)\)', clean_json_string)
    if point_match:
        return [int(point_match.group(1)), int(point_match.group(2))]
    
    # 首先尝试直接解析
    try:
        parsed = json.loads(clean_json_string)
        return normalize_json_object(parsed)
    except (json.JSONDecodeError, ValueError):
        pass

    # 尝试修复后解析
    try:
        repaired = repair_json(clean_json_string)
        parsed = json.loads(repaired)
        return normalize_json_object(parsed)
    except Exception:
        pass

    # 豆包/UI-TARS 特殊处理
    if model_family == 'doubao-vision' or is_ui_tars(model_family):
        json_string = preprocess_doubao_bbox_json(clean_json_string)
        try:
            repaired = repair_json(json_string)
            parsed = json.loads(repaired)
            return normalize_json_object(parsed)
        except Exception:
            pass

    logger.error(f"Failed to parse JSON: {text[:200]}...")
    return None


class ModelConfig:
    """模型配置"""

    def __init__(
        self,
        model_name: str = "qwen-vl-max",
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        timeout: int = 60000,  # 毫秒
        retry_count: int = 1,
        retry_interval: int = 2000,  # 毫秒
        http_proxy: Optional[str] = None,
        model_description: Optional[str] = None,
        intent: Optional[str] = None,
        extra_config: Optional[Dict[str, Any]] = None,
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
        self.model_description = model_description or model_name
        self.intent = intent
        self.extra_config = extra_config or {}


def create_chat_client(model_config: ModelConfig) -> OpenAI:
    """
    创建 OpenAI 客户端

    Args:
        model_config: 模型配置

    Returns:
        OpenAI 客户端实例
    """
    client_kwargs = {
        "api_key": model_config.api_key,
        "timeout": model_config.timeout / 1000,  # 转换为秒
    }

    # 设置 base_url
    if model_config.base_url:
        client_kwargs["base_url"] = model_config.base_url

    # 设置代理
    if model_config.http_proxy:
        import httpx
        client_kwargs["http_client"] = httpx.Client(
            proxy=model_config.http_proxy
        )
        logger.debug(f"Using HTTP proxy: {model_config.http_proxy}")

    # 应用额外配置
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
    messages: List[ChatCompletionMessageParam],
    model_config: ModelConfig,
    stream: bool = False,
    on_chunk: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
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

    start_time = time.time()
    max_attempts = model_config.retry_count + 1
    last_error: Optional[Exception] = None

    # 准备请求参数
    request_params = {
        "model": model_config.model_name,
        "messages": messages,
        "temperature": model_config.temperature,
        "max_tokens": model_config.max_tokens,
    }

    # 千问 VL 特定配置
    if "qwen" in model_config.model_name.lower() and "vl" in model_config.model_name.lower():
        request_params["extra_body"] = {
            "vl_high_resolution_images": True
        }

    logger.info(f"Sending request to {model_config.model_name}")

    # 重试逻辑
    for attempt in range(1, max_attempts + 1):
        try:
            if stream and on_chunk:
                # 流式调用
                accumulated = ""
                usage = None

                response_stream = client.chat.completions.create(
                    **request_params,
                    stream=True
                )

                for chunk in response_stream:
                    if chunk.choices and len(chunk.choices) > 0:
                        delta = chunk.choices[0].delta
                        if delta.content:
                            accumulated += delta.content
                            on_chunk(delta.content)

                        # 检查是否有 usage 信息
                        if hasattr(chunk, 'usage') and chunk.usage:
                            usage = chunk.usage

                time_cost = (time.time() - start_time) * 1000

                return {
                    "content": accumulated,
                    "usage": build_usage_info(usage, time_cost, model_config) if usage else None,
                    "isStreamed": True,
                }

            else:
                # 非流式调用
                response: ChatCompletion = client.chat.completions.create(
                    **request_params
                )

                time_cost = (time.time() - start_time) * 1000

                # 提取响应内容
                if not response.choices:
                    raise ValueError(
                        f"Invalid response from LLM service: {response}"
                    )

                content = response.choices[0].message.content or ""

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
                raise last_error

    # 不应该到达这里，但为了类型检查
    raise RuntimeError("Unexpected error in call_ai")


def extract_json_from_response(content: str) -> Optional[Dict[str, Any]]:
    """
    从 AI 响应中提取 JSON

    Args:
        content: AI 响应内容

    Returns:
        解析后的 JSON 对象，失败返回 None
    """
    return safe_parse_json_with_repair(content)


__all__ = [
    "ModelConfig",
    "create_chat_client",
    "call_ai",
    "extract_json_from_response",
    "safe_parse_json_with_repair",
]
