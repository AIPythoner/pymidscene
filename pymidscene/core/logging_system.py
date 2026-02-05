"""
多组件日志系统 - 与 JS 版本 Midscene 对齐

生成多个日志文件，对应 JS 版本的:
- agent.log
- ai-call.log
- cache.log
- web-page.log
等

目录结构:
midscene_run/
├── cache/          # 缓存文件 (YAML格式)
├── dump/           # JSON数据转储
├── log/            # 文本日志 (多个组件日志)
├── output/         # 输出文件
└── report/         # HTML可视化报告
"""

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any
import json


class MidsceneLogManager:
    """
    Midscene 多组件日志管理器

    与 JS 版本对齐，为不同组件创建独立的日志文件:
    - agent.log: Agent 执行日志
    - ai-call.log: AI 调用日志
    - cache.log: 缓存操作日志
    - web-page.log: 页面操作日志
    - planning.log: 规划日志
    """

    # 日志组件定义
    COMPONENTS = {
        "agent": "agent.log",
        "ai-call": "ai-call.log",
        "cache": "cache.log",
        "web-page": "web-page.log",
        "planning": "planning.log",
        "task-runner": "task-runner.log",
        "img": "img.log",
    }

    # 日志格式 - 与 JS 版本对齐
    LOG_FORMAT = "[{timestamp}] {message}"

    def __init__(self, log_dir: Optional[Path] = None):
        """
        初始化日志管理器

        Args:
            log_dir: 日志目录路径
        """
        self.log_dir = log_dir or Path.cwd() / "midscene_run" / "log"
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self._loggers: Dict[str, logging.Logger] = {}
        self._handlers: Dict[str, logging.FileHandler] = {}

        self._setup_loggers()

    def _setup_loggers(self):
        """设置所有组件的日志器"""
        for component, filename in self.COMPONENTS.items():
            self._create_component_logger(component, filename)

    def _create_component_logger(self, component: str, filename: str):
        """创建单个组件的日志器"""
        logger = logging.getLogger(f"midscene.{component}")
        logger.setLevel(logging.DEBUG)
        logger.propagate = False  # 不传播到父日志器

        # 移除已有的处理器
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)

        # 创建文件处理器
        log_path = self.log_dir / filename
        handler = logging.FileHandler(log_path, encoding='utf-8')
        handler.setLevel(logging.DEBUG)

        # 自定义格式器
        formatter = MidsceneFormatter()
        handler.setFormatter(formatter)

        logger.addHandler(handler)

        self._loggers[component] = logger
        self._handlers[component] = handler

    def get_logger(self, component: str) -> logging.Logger:
        """
        获取指定组件的日志器

        Args:
            component: 组件名称

        Returns:
            日志器实例
        """
        if component not in self._loggers:
            # 动态创建新组件的日志器
            filename = f"{component}.log"
            self._create_component_logger(component, filename)

        return self._loggers[component]

    def log(self, component: str, message: str, level: str = "info", **kwargs):
        """
        记录日志

        Args:
            component: 组件名称
            message: 日志消息
            level: 日志级别
            **kwargs: 额外数据（将被格式化为 JSON）
        """
        logger = self.get_logger(component)

        # 如果有额外数据，附加到消息
        if kwargs:
            try:
                extra_str = json.dumps(kwargs, ensure_ascii=False, indent=2)
                message = f"{message}\n{extra_str}"
            except:
                pass

        log_func = getattr(logger, level, logger.info)
        log_func(message)

    def agent(self, message: str, **kwargs):
        """Agent 日志"""
        self.log("agent", message, **kwargs)

    def ai_call(self, message: str, **kwargs):
        """AI 调用日志"""
        self.log("ai-call", message, **kwargs)

    def cache(self, message: str, **kwargs):
        """缓存日志"""
        self.log("cache", message, **kwargs)

    def web_page(self, message: str, **kwargs):
        """页面操作日志"""
        self.log("web-page", message, **kwargs)

    def planning(self, message: str, **kwargs):
        """规划日志"""
        self.log("planning", message, **kwargs)

    def close(self):
        """关闭所有日志处理器"""
        for handler in self._handlers.values():
            handler.close()


class MidsceneFormatter(logging.Formatter):
    """
    Midscene 日志格式器 - 与 JS 版本对齐

    格式: [2025-12-11T16:58:34.413+08:00] 消息内容
    """

    def format(self, record: logging.LogRecord) -> str:
        # 生成 ISO 格式的时间戳（带时区）
        timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S.") + \
                   f"{datetime.now().microsecond // 1000:03d}" + \
                   datetime.now().strftime("%z") or "+00:00"

        # 如果没有时区信息，添加本地时区
        if not timestamp.endswith("+") and "+" not in timestamp[-6:] and "-" not in timestamp[-6:]:
            import time
            offset = time.timezone if time.daylight == 0 else time.altzone
            hours, remainder = divmod(abs(offset), 3600)
            minutes = remainder // 60
            sign = "-" if offset > 0 else "+"
            timestamp = timestamp[:-3] + f"{sign}{hours:02d}:{minutes:02d}"

        return f"[{timestamp}] {record.getMessage()}"


# 全局日志管理器实例
_global_log_manager: Optional[MidsceneLogManager] = None


def get_log_manager(log_dir: Optional[Path] = None) -> MidsceneLogManager:
    """
    获取全局日志管理器实例

    Args:
        log_dir: 日志目录（首次调用时设置）

    Returns:
        MidsceneLogManager 实例
    """
    global _global_log_manager

    if _global_log_manager is None:
        _global_log_manager = MidsceneLogManager(log_dir)

    return _global_log_manager


def reset_log_manager():
    """重置全局日志管理器"""
    global _global_log_manager
    if _global_log_manager:
        _global_log_manager.close()
    _global_log_manager = None


__all__ = [
    "MidsceneLogManager",
    "MidsceneFormatter",
    "get_log_manager",
    "reset_log_manager",
]
