"""
配置工厂 - 对齐 @midscene/cli/src/config-factory.ts。

把 ``CLI flag > config-yaml 字段 > 默认值`` 三层合并成一个
:class:`BatchRunnerConfig`,并把文件 glob 展开成绝对路径列表。
``global_config`` (web/android/ios) 之后会叠加到每个脚本自身的同名块上。
"""

from __future__ import annotations

import glob
import os
from dataclasses import dataclass, field
from typing import Any

import yaml

from .args import CliOptions
from .yaml_script import interpolate_env_vars

# 对齐 JS defaultConfig。
DEFAULT_CONCURRENT = 1
DEFAULT_CONTINUE_ON_ERROR = False
DEFAULT_SHARE_BROWSER_CONTEXT = False
DEFAULT_HEADED = False
DEFAULT_KEEP_WINDOW = False
DEFAULT_DOTENV_OVERRIDE = False
DEFAULT_DOTENV_DEBUG = False


@dataclass
class BatchRunnerConfig:
    """一次批量运行的最终配置。"""

    files: list[str]
    concurrent: int = DEFAULT_CONCURRENT
    continue_on_error: bool = DEFAULT_CONTINUE_ON_ERROR
    summary: str = "summary.json"
    share_browser_context: bool = DEFAULT_SHARE_BROWSER_CONTEXT
    headed: bool = DEFAULT_HEADED
    keep_window: bool = DEFAULT_KEEP_WINDOW
    dotenv_override: bool = DEFAULT_DOTENV_OVERRIDE
    dotenv_debug: bool = DEFAULT_DOTENV_DEBUG
    global_config: dict = field(default_factory=dict)


def _deep_merge(base: dict | None, override: dict | None) -> dict:
    """递归合并两个 dict,override 优先(对齐 lodash.merge 的子集)。"""
    result: dict = dict(base or {})
    for key, value in (override or {}).items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def match_yaml_files(file_glob: str, cwd: str | None = None) -> list[str]:
    """把一个路径/目录/glob 展开成排序后的绝对 yaml 文件列表。

    对齐 JS ``matchYamlFiles``:目录 -> ``<dir>/**/*.{yml,yaml}``;过滤
    .yml/.yaml;排除 node_modules;字典序排序;返回绝对路径。
    """
    base = cwd or os.getcwd()
    candidate = file_glob
    if not os.path.isabs(candidate):
        candidate = os.path.join(base, candidate)

    patterns: list[str]
    if os.path.isdir(candidate):
        patterns = [
            os.path.join(candidate, "**", "*.yml"),
            os.path.join(candidate, "**", "*.yaml"),
        ]
    else:
        patterns = [candidate]

    matched: list[str] = []
    for pattern in patterns:
        for hit in glob.glob(pattern, recursive=True):
            if os.path.isdir(hit):
                continue
            lower = hit.lower()
            if not (lower.endswith(".yml") or lower.endswith(".yaml")):
                continue
            if "node_modules" in hit.replace("\\", "/").split("/"):
                continue
            matched.append(os.path.abspath(hit))

    # 去重但保持排序;同一 glob 内重复匹配只算一次。
    seen: set[str] = set()
    unique = []
    for path in sorted(matched):
        if path not in seen:
            seen.add(path)
            unique.append(path)
    return unique


def expand_file_patterns(
    patterns: list[str], base_dir: str | None = None
) -> list[str]:
    """展开多个 pattern;**保留重复**(同一文件列两次就跑两次,对齐 JS)。"""
    files: list[str] = []
    for pattern in patterns:
        matched = match_yaml_files(pattern, cwd=base_dir)
        if not matched:
            # 单个 pattern 无匹配只警告,不报错(对齐 JS expandFilePatterns)。
            from ..shared.logger import logger

            logger.warning(f"No yaml files matched pattern: {pattern}")
            continue
        files.extend(matched)
    return files


def _pick(cli_value: Any, file_value: Any, default: Any) -> Any:
    """三层优先级:CLI > 配置文件 > 默认。``None`` 视为未设置。"""
    if cli_value is not None:
        return cli_value
    if file_value is not None:
        return file_value
    return default


def _build_global_config(
    file_env: dict, options: CliOptions
) -> dict:
    """合并 web/android/ios 目标环境:CLI 覆盖配置文件。"""
    global_config: dict = {}
    for key in ("web", "android", "ios"):
        merged = _deep_merge(
            file_env.get(key), getattr(options, key) or None
        )
        if merged:
            global_config[key] = merged
    return global_config


def create_files_config(
    patterns: list[str], options: CliOptions, timestamp: int
) -> BatchRunnerConfig:
    """无 config 文件模式:从 cwd 展开 patterns,默认 summary=summary-<ts>.json。"""
    files = expand_file_patterns(patterns, base_dir=os.getcwd())
    keep_window = _pick(options.keep_window, None, DEFAULT_KEEP_WINDOW)
    headed = _pick(options.headed, None, DEFAULT_HEADED)
    return BatchRunnerConfig(
        files=files,
        concurrent=_pick(options.concurrent, None, DEFAULT_CONCURRENT),
        continue_on_error=_pick(
            options.continue_on_error, None, DEFAULT_CONTINUE_ON_ERROR
        ),
        summary=options.summary or f"summary-{timestamp}.json",
        share_browser_context=_pick(
            options.share_browser_context, None, DEFAULT_SHARE_BROWSER_CONTEXT
        ),
        headed=bool(keep_window or headed),
        keep_window=bool(keep_window),
        dotenv_override=_pick(
            options.dotenv_override, None, DEFAULT_DOTENV_OVERRIDE
        ),
        dotenv_debug=_pick(options.dotenv_debug, None, DEFAULT_DOTENV_DEBUG),
        global_config=_build_global_config({}, options),
    )


def create_config(
    config_yaml_path: str, options: CliOptions, timestamp: int
) -> BatchRunnerConfig:
    """config 文件模式:读取索引 yaml(需含 files: 数组),CLI 覆盖其字段。"""
    with open(config_yaml_path, encoding="utf-8") as fh:
        content = fh.read()
    parsed = yaml.safe_load(interpolate_env_vars(content)) or {}
    if not isinstance(parsed, dict):
        raise ValueError("Config YAML must be a mapping")

    file_patterns = parsed.get("files")
    if not isinstance(file_patterns, list):
        raise ValueError('Config YAML must contain a "files" array')

    base_path = os.path.dirname(os.path.abspath(config_yaml_path))
    # --files 覆盖 config 内的 files;两者都相对 config 文件目录解析(对齐 JS:
    # createConfig 用 dirname(resolve(configYamlPath)) 作 --files 的 base)。
    if options.files:
        files = expand_file_patterns(options.files, base_dir=base_path)
    else:
        files = expand_file_patterns(file_patterns, base_dir=base_path)
    if not files:
        raise ValueError(
            'No YAML files found matching the patterns in "files"'
        )

    config_name = os.path.splitext(os.path.basename(config_yaml_path))[0]
    keep_window = _pick(
        options.keep_window, parsed.get("keepWindow"), DEFAULT_KEEP_WINDOW
    )
    headed = _pick(options.headed, parsed.get("headed"), DEFAULT_HEADED)

    return BatchRunnerConfig(
        files=files,
        concurrent=_pick(
            options.concurrent, parsed.get("concurrent"), DEFAULT_CONCURRENT
        ),
        continue_on_error=_pick(
            options.continue_on_error,
            parsed.get("continueOnError"),
            DEFAULT_CONTINUE_ON_ERROR,
        ),
        summary=options.summary
        or parsed.get("summary")
        or f"{config_name}-{timestamp}.json",
        share_browser_context=_pick(
            options.share_browser_context,
            parsed.get("shareBrowserContext"),
            DEFAULT_SHARE_BROWSER_CONTEXT,
        ),
        headed=bool(keep_window or headed),
        keep_window=bool(keep_window),
        dotenv_override=_pick(
            options.dotenv_override,
            parsed.get("dotenvOverride"),
            DEFAULT_DOTENV_OVERRIDE,
        ),
        dotenv_debug=_pick(
            options.dotenv_debug, parsed.get("dotenvDebug"), DEFAULT_DOTENV_DEBUG
        ),
        global_config=_build_global_config(parsed, options),
    )


__all__ = [
    "BatchRunnerConfig",
    "match_yaml_files",
    "expand_file_patterns",
    "create_files_config",
    "create_config",
]
