"""
测试日志系统
"""

import pytest
from pymidscene.shared.logger import logger, MidsceneLogger


def test_logger_singleton():
    """测试日志器是单例模式"""
    logger1 = MidsceneLogger()
    logger2 = MidsceneLogger()
    assert logger1 is logger2


def test_logger_basic_logging():
    """测试基础日志功能"""
    # 这些调用不应该抛出异常
    logger.debug("Debug message")
    logger.info("Info message")
    logger.warning("Warning message")
    logger.error("Error message")
    logger.critical("Critical message")


def test_logger_set_level():
    """测试设置日志级别"""
    logger.set_level("DEBUG")
    logger.set_level("INFO")
    logger.set_level("WARNING")
    logger.set_level("ERROR")
