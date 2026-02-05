"""
环境配置模块

对应 packages/shared/src/env/
"""

from .constants import (
    MIDSCENE_MODEL_NAME,
    MIDSCENE_MODEL_BASE_URL,
    MIDSCENE_MODEL_API_KEY,
    MIDSCENE_MODEL_FAMILY,
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
    MODEL_FAMILY_VALUES,
    INTENT_DEFAULT,
    INTENT_INSIGHT,
    INTENT_PLANNING,
    ModelConfigKeys,
    DEFAULT_MODEL_CONFIG_KEYS,
    INSIGHT_MODEL_CONFIG_KEYS,
    PLANNING_MODEL_CONFIG_KEYS,
    KEYS_MAP,
)

from .model_config_manager import (
    ModelConfig,
    ModelConfigManager,
    TIntent,
    get_global_model_config_manager,
    legacy_config_to_model_family,
    validate_model_family,
)


__all__ = [
    # Constants
    "MIDSCENE_MODEL_NAME",
    "MIDSCENE_MODEL_BASE_URL",
    "MIDSCENE_MODEL_API_KEY",
    "MIDSCENE_MODEL_FAMILY",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "MODEL_FAMILY_VALUES",
    "INTENT_DEFAULT",
    "INTENT_INSIGHT",
    "INTENT_PLANNING",
    "ModelConfigKeys",
    "DEFAULT_MODEL_CONFIG_KEYS",
    "INSIGHT_MODEL_CONFIG_KEYS",
    "PLANNING_MODEL_CONFIG_KEYS",
    "KEYS_MAP",
    # Model Config Manager
    "ModelConfig",
    "ModelConfigManager",
    "TIntent",
    "get_global_model_config_manager",
    "legacy_config_to_model_family",
    "validate_model_family",
]
