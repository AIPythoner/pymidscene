"""
模型配置管理器 - 对应 packages/shared/src/env/model-config-manager.ts

管理不同 intent（default、insight、planning）的模型配置。
"""

import os
import json
from typing import Dict, Any, Optional, Literal
from dataclasses import dataclass, field

from .constants import (
    KEYS_MAP,
    DEFAULT_MODEL_CONFIG_KEYS_LEGACY,
    MODEL_FAMILY_VALUES,
    INTENT_DEFAULT,
    INTENT_INSIGHT,
    INTENT_PLANNING,
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
    MIDSCENE_MODEL_API_KEY,
    MIDSCENE_MODEL_BASE_URL,
    MIDSCENE_USE_DOUBAO_VISION,
    MIDSCENE_USE_QWEN_VL,
    MIDSCENE_USE_QWEN3_VL,
    MIDSCENE_USE_VLM_UI_TARS,
    MIDSCENE_USE_GEMINI,
    ModelConfigKeys,
)
from ..logger import logger


TIntent = Literal["default", "insight", "planning"]


@dataclass
class ModelConfig:
    """模型配置"""
    model_name: str
    openai_base_url: str
    openai_api_key: str
    model_family: Optional[str] = None
    intent: str = "default"
    timeout: Optional[int] = None
    temperature: float = 0.0
    retry_count: int = 1
    retry_interval: int = 2000
    socks_proxy: Optional[str] = None
    http_proxy: Optional[str] = None
    openai_extra_config: Optional[Dict[str, Any]] = None
    model_description: str = ""


def legacy_config_to_model_family(provider: Dict[str, Optional[str]]) -> Optional[str]:
    """
    将旧版环境变量转换为模型家族

    对应 JS 版本的 legacyConfigToModelFamily
    """
    is_doubao = provider.get(MIDSCENE_USE_DOUBAO_VISION)
    is_qwen = provider.get(MIDSCENE_USE_QWEN_VL)
    is_qwen3 = provider.get(MIDSCENE_USE_QWEN3_VL)
    is_ui_tars = provider.get(MIDSCENE_USE_VLM_UI_TARS)
    is_gemini = provider.get(MIDSCENE_USE_GEMINI)

    enabled_modes = [
        MIDSCENE_USE_DOUBAO_VISION if is_doubao else None,
        MIDSCENE_USE_QWEN_VL if is_qwen else None,
        MIDSCENE_USE_QWEN3_VL if is_qwen3 else None,
        MIDSCENE_USE_VLM_UI_TARS if is_ui_tars else None,
        MIDSCENE_USE_GEMINI if is_gemini else None,
    ]
    enabled_modes = [m for m in enabled_modes if m]

    if len(enabled_modes) > 1:
        raise ValueError(
            f"Only one vision mode can be enabled at a time. "
            f"Currently enabled modes: {', '.join(enabled_modes)}. "
            f"Please disable all but one mode."
        )

    if is_qwen3:
        return "qwen3-vl"
    if is_qwen:
        return "qwen2.5-vl"
    if is_doubao:
        return "doubao-vision"
    if is_gemini:
        return "gemini"

    if is_ui_tars:
        if is_ui_tars == "1":
            return "vlm-ui-tars"
        elif is_ui_tars in ("DOUBAO", "DOUBAO-1.5"):
            return "vlm-ui-tars-doubao-1.5"
        else:
            return "vlm-ui-tars-doubao"

    return None


def validate_model_family(model_family: Optional[str]) -> None:
    """验证模型家族值"""
    if model_family and model_family not in MODEL_FAMILY_VALUES:
        raise ValueError(f"Invalid MIDSCENE_MODEL_FAMILY value: {model_family}")


def parse_openai_sdk_config(
    keys: ModelConfigKeys,
    provider: Dict[str, Optional[str]],
    use_legacy_logic: bool = False
) -> ModelConfig:
    """
    解析 OpenAI SDK 配置

    对应 JS 版本的 parseOpenaiSdkConfig
    """
    # 旧版兼容
    legacy_api_key = provider.get(OPENAI_API_KEY) if use_legacy_logic else None
    legacy_base_url = provider.get(OPENAI_BASE_URL) if use_legacy_logic else None
    legacy_model_family = legacy_config_to_model_family(provider) if use_legacy_logic else None

    # 获取配置值
    model_family = provider.get(keys.model_family) or legacy_model_family
    openai_api_key = provider.get(keys.openai_api_key) or legacy_api_key or ""
    openai_base_url = provider.get(keys.openai_base_url) or legacy_base_url or ""
    model_name = provider.get(keys.model_name) or ""

    # 验证模型家族
    validate_model_family(model_family)

    # 解析数值配置
    timeout = None
    if provider.get(keys.timeout):
        try:
            timeout = int(provider[keys.timeout])
        except (ValueError, TypeError):
            pass

    temperature = 0.0
    if provider.get(keys.temperature):
        try:
            temperature = float(provider[keys.temperature])
        except (ValueError, TypeError):
            pass

    retry_count = 1
    if provider.get(keys.retry_count):
        try:
            val = int(provider[keys.retry_count])
            if val < 0:
                raise ValueError(f"{keys.retry_count} must be non-negative, got {val}")
            retry_count = val
        except (ValueError, TypeError):
            pass

    retry_interval = 2000
    if provider.get(keys.retry_interval):
        try:
            val = int(provider[keys.retry_interval])
            if val < 0:
                raise ValueError(f"{keys.retry_interval} must be non-negative, got {val}")
            retry_interval = val
        except (ValueError, TypeError):
            pass

    # 解析额外配置
    openai_extra_config = None
    extra_config_str = provider.get(keys.openai_extra_config)
    if extra_config_str:
        try:
            openai_extra_config = json.loads(extra_config_str)
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse {keys.openai_extra_config} as JSON")

    # 生成模型描述
    model_description = f"{model_family} mode" if model_family else ""

    return ModelConfig(
        model_name=model_name,
        openai_base_url=openai_base_url,
        openai_api_key=openai_api_key,
        model_family=model_family,
        timeout=timeout,
        temperature=temperature,
        retry_count=retry_count,
        retry_interval=retry_interval,
        socks_proxy=provider.get(keys.socks_proxy),
        http_proxy=provider.get(keys.http_proxy),
        openai_extra_config=openai_extra_config,
        model_description=model_description,
    )


def decide_model_config_from_intent(
    intent: TIntent,
    config_map: Dict[str, Optional[str]]
) -> Optional[ModelConfig]:
    """
    根据 intent 决定模型配置

    对应 JS 版本的 decideModelConfigFromIntentConfig
    """
    keys = KEYS_MAP.get(intent)
    if not keys:
        return None

    model_name = config_map.get(keys.model_name)
    if not model_name:
        logger.debug(f"No model_name found for intent {intent}")
        return None

    config = parse_openai_sdk_config(
        keys=keys,
        provider=config_map,
        use_legacy_logic=(intent == INTENT_DEFAULT)
    )
    config.intent = intent

    if not config.openai_base_url:
        raise ValueError(
            f"Failed to get base URL of model (intent={intent}). "
            f"See https://midscenejs.com/model-strategy"
        )

    if not config.model_name:
        logger.warning(
            f"model_name is not set for intent {intent}, "
            f"this may cause unexpected behavior."
        )

    return config


class ModelConfigManager:
    """
    模型配置管理器

    对应 JS 版本的 ModelConfigManager 类。
    支持通过环境变量或传入配置字典来配置模型。

    使用方式：
    1. 通过环境变量（默认）：
        os.environ["MIDSCENE_MODEL_NAME"] = "qwen-vl-max"
        os.environ["MIDSCENE_MODEL_API_KEY"] = "your-key"
        os.environ["MIDSCENE_MODEL_BASE_URL"] = "https://..."
        os.environ["MIDSCENE_MODEL_FAMILY"] = "qwen2.5-vl"

        manager = ModelConfigManager()

    2. 通过配置字典：
        manager = ModelConfigManager(model_config={
            "MIDSCENE_MODEL_NAME": "qwen-vl-max",
            "MIDSCENE_MODEL_API_KEY": "your-key",
            "MIDSCENE_MODEL_BASE_URL": "https://...",
            "MIDSCENE_MODEL_FAMILY": "qwen2.5-vl",
        })
    """

    def __init__(self, model_config: Optional[Dict[str, Any]] = None):
        """
        初始化模型配置管理器

        Args:
            model_config: 可选的配置字典，如果提供则使用隔离模式
        """
        self._model_config = model_config
        self._model_config_map: Optional[Dict[TIntent, ModelConfig]] = None
        self._is_initialized = False
        self._isolated_mode = model_config is not None

    def _get_env_config(self) -> Dict[str, Optional[str]]:
        """获取所有环境变量配置"""
        return dict(os.environ)

    def _normalize_model_config(
        self,
        config: Dict[str, Any]
    ) -> Dict[str, Optional[str]]:
        """规范化模型配置"""
        result: Dict[str, Optional[str]] = {}
        for key, value in config.items():
            if value is None:
                continue
            result[key] = str(value)
        return result

    def _initialize(self) -> None:
        """初始化配置"""
        if self._is_initialized:
            return

        if self._model_config:
            self._isolated_mode = True
            config_map = self._normalize_model_config(self._model_config)
        else:
            config_map = self._get_env_config()

        # 解析 default 配置
        default_config = decide_model_config_from_intent(INTENT_DEFAULT, config_map)
        if not default_config:
            raise ValueError(
                "Default model config is not found. "
                "Please set MIDSCENE_MODEL_NAME and related environment variables, "
                "or pass model_config to the constructor."
            )

        # 解析 insight 配置（回退到 default）
        insight_config = decide_model_config_from_intent(INTENT_INSIGHT, config_map)

        # 解析 planning 配置（回退到 default）
        planning_config = decide_model_config_from_intent(INTENT_PLANNING, config_map)

        self._model_config_map = {
            INTENT_DEFAULT: default_config,
            INTENT_INSIGHT: insight_config or default_config,
            INTENT_PLANNING: planning_config or default_config,
        }

        self._is_initialized = True

    def clear_model_config_map(self) -> None:
        """清除配置缓存（仅非隔离模式可用）"""
        if self._isolated_mode:
            raise RuntimeError(
                "ModelConfigManager works in isolated mode, "
                "clearModelConfigMap should not be called"
            )
        self._is_initialized = False
        self._model_config_map = None

    def get_model_config(self, intent: TIntent) -> ModelConfig:
        """
        获取指定 intent 的模型配置

        Args:
            intent: 意图类型（default、insight、planning）

        Returns:
            模型配置
        """
        if not self._is_initialized:
            self._initialize()

        if not self._model_config_map:
            raise RuntimeError("Model config map is not initialized")

        return self._model_config_map[intent]

    def throw_error_if_non_vl_model(self) -> None:
        """如果不是 VL 模型则抛出错误"""
        config = self.get_model_config(INTENT_DEFAULT)
        if not config.model_family:
            raise ValueError(
                "MIDSCENE_MODEL_FAMILY is not set to a visual language model (VL model), "
                "the element localization cannot be achieved. "
                "Check your model configuration."
            )


# 全局配置管理器实例
global_model_config_manager: Optional[ModelConfigManager] = None


def get_global_model_config_manager() -> ModelConfigManager:
    """获取全局模型配置管理器"""
    global global_model_config_manager
    if global_model_config_manager is None:
        global_model_config_manager = ModelConfigManager()
    return global_model_config_manager


__all__ = [
    "ModelConfig",
    "ModelConfigManager",
    "TIntent",
    "get_global_model_config_manager",
    "legacy_config_to_model_family",
    "validate_model_family",
]
