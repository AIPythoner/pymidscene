"""
日志系统 - 对应 packages/shared/src/logger.ts

提供统一的日志记录功能。
"""

import logging
import sys
from typing import Optional
from pathlib import Path


class MidsceneLogger:
    """Midscene 日志器"""

    _instance: Optional['MidsceneLogger'] = None
    _logger: Optional[logging.Logger] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._logger is None:
            self._setup_logger()

    def _setup_logger(self):
        """设置日志器"""
        self._logger = logging.getLogger('pymidscene')
        self._logger.setLevel(logging.INFO)

        # 控制台处理器
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)

        # 格式化器
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        console_handler.setFormatter(formatter)

        # 添加处理器
        if not self._logger.handlers:
            self._logger.addHandler(console_handler)

    def set_level(self, level: str):
        """设置日志级别"""
        level_map = {
            'DEBUG': logging.DEBUG,
            'INFO': logging.INFO,
            'WARNING': logging.WARNING,
            'ERROR': logging.ERROR,
            'CRITICAL': logging.CRITICAL,
        }
        self._logger.setLevel(level_map.get(level.upper(), logging.INFO))

    def add_file_handler(self, log_file: str):
        """添加文件处理器"""
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)

        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(formatter)

        self._logger.addHandler(file_handler)

    def debug(self, message: str, *args, **kwargs):
        """调试日志"""
        self._logger.debug(message, *args, **kwargs)

    def info(self, message: str, *args, **kwargs):
        """信息日志"""
        self._logger.info(message, *args, **kwargs)

    def warning(self, message: str, *args, **kwargs):
        """警告日志"""
        self._logger.warning(message, *args, **kwargs)

    def error(self, message: str, *args, **kwargs):
        """错误日志"""
        self._logger.error(message, *args, **kwargs)

    def critical(self, message: str, *args, **kwargs):
        """严重错误日志"""
        self._logger.critical(message, *args, **kwargs)


# 全局日志器实例
logger = MidsceneLogger()


__all__ = ['logger', 'MidsceneLogger']
