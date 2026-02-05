"""
Midscene Run 目录管理器 - 管理 midscene_run 目录结构

对应 JS 版本的目录结构:
midscene_run/
├── cache/          # 缓存文件 (YAML格式)
├── dump/           # JSON数据转储
├── log/            # 文本日志
├── output/         # 输出文件
└── report/         # HTML可视化报告
"""

import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..shared.logger import logger


class MidsceneRunManager:
    """
    Midscene Run 目录管理器

    在当前工作目录或指定目录下创建和管理 midscene_run 目录结构。
    与 JS 版本保持一致的目录布局。
    """

    RUN_DIR_NAME = "midscene_run"

    # 子目录名称
    CACHE_DIR = "cache"
    DUMP_DIR = "dump"
    LOG_DIR = "log"
    OUTPUT_DIR = "output"
    REPORT_DIR = "report"

    def __init__(self, base_dir: Optional[str] = None):
        """
        初始化目录管理器

        Args:
            base_dir: 基础目录路径，默认为当前工作目录
        """
        self.base_dir = Path(base_dir) if base_dir else Path.cwd()
        self.run_dir = self.base_dir / self.RUN_DIR_NAME
        self._ensure_directories()

        logger.debug(f"MidsceneRunManager initialized: {self.run_dir}")

    def _ensure_directories(self) -> None:
        """确保所有子目录存在"""
        directories = [
            self.cache_dir,
            self.dump_dir,
            self.log_dir,
            self.output_dir,
            self.report_dir,
        ]

        for dir_path in directories:
            dir_path.mkdir(parents=True, exist_ok=True)

        logger.debug(f"Ensured directories exist in: {self.run_dir}")

    @property
    def cache_dir(self) -> Path:
        """缓存目录路径"""
        return self.run_dir / self.CACHE_DIR

    @property
    def dump_dir(self) -> Path:
        """JSON转储目录路径"""
        return self.run_dir / self.DUMP_DIR

    @property
    def log_dir(self) -> Path:
        """日志目录路径"""
        return self.run_dir / self.LOG_DIR

    @property
    def output_dir(self) -> Path:
        """输出目录路径"""
        return self.run_dir / self.OUTPUT_DIR

    @property
    def report_dir(self) -> Path:
        """HTML报告目录路径"""
        return self.run_dir / self.REPORT_DIR

    def get_cache_file_path(self, cache_id: str) -> Path:
        """
        获取缓存文件路径

        Args:
            cache_id: 缓存ID

        Returns:
            缓存文件完整路径
        """
        return self.cache_dir / f"{cache_id}.cache.yaml"

    def get_dump_file_path(self, session_id: str) -> Path:
        """
        获取JSON转储文件路径

        Args:
            session_id: 会话ID

        Returns:
            转储文件完整路径
        """
        return self.dump_dir / f"{session_id}.json"

    def get_log_file_path(self, date: Optional[datetime] = None) -> Path:
        """
        获取日志文件路径

        Args:
            date: 日期，默认为今天

        Returns:
            日志文件完整路径
        """
        if date is None:
            date = datetime.now()
        date_str = date.strftime("%Y-%m-%d")
        return self.log_dir / f"{date_str}.log"

    def generate_report_filename(
        self,
        driver_type: str = "playwright",
        timestamp: Optional[datetime] = None,
        session_id: Optional[str] = None
    ) -> str:
        """
        生成报告文件名（与JS版本格式对齐）

        格式: {driver}-{YYYY-MM-DD_HH-MM-SS}-{uuid8}.html

        Args:
            driver_type: 驱动类型 (playwright, selenium, appium等)
            timestamp: 时间戳，默认为当前时间
            session_id: 会话ID，默认生成新的UUID

        Returns:
            报告文件名
        """
        if timestamp is None:
            timestamp = datetime.now()

        if session_id is None:
            session_id = uuid.uuid4().hex[:8]
        else:
            # 取前8位
            session_id = session_id[:8]

        time_str = timestamp.strftime("%Y-%m-%d_%H-%M-%S")
        return f"{driver_type}-{time_str}-{session_id}.html"

    def get_report_file_path(
        self,
        driver_type: str = "playwright",
        timestamp: Optional[datetime] = None,
        session_id: Optional[str] = None
    ) -> Path:
        """
        获取报告文件完整路径

        Args:
            driver_type: 驱动类型
            timestamp: 时间戳
            session_id: 会话ID

        Returns:
            报告文件完整路径
        """
        filename = self.generate_report_filename(driver_type, timestamp, session_id)
        return self.report_dir / filename

    def get_output_file_path(self, filename: str) -> Path:
        """
        获取输出文件路径

        Args:
            filename: 文件名

        Returns:
            输出文件完整路径
        """
        return self.output_dir / filename

    def list_reports(self) -> list:
        """
        列出所有HTML报告文件

        Returns:
            报告文件路径列表，按修改时间倒序排列
        """
        reports = list(self.report_dir.glob("*.html"))
        # 按修改时间倒序排列
        reports.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        return reports

    def list_dumps(self) -> list:
        """
        列出所有JSON转储文件

        Returns:
            转储文件路径列表
        """
        return list(self.dump_dir.glob("*.json"))

    def list_caches(self) -> list:
        """
        列出所有缓存文件

        Returns:
            缓存文件路径列表
        """
        return list(self.cache_dir.glob("*.cache.yaml"))

    def clean_old_reports(self, keep_count: int = 10) -> int:
        """
        清理旧的报告文件，保留最近的N个

        Args:
            keep_count: 保留的报告数量

        Returns:
            删除的文件数量
        """
        reports = self.list_reports()

        if len(reports) <= keep_count:
            return 0

        to_delete = reports[keep_count:]
        deleted_count = 0

        for report_path in to_delete:
            try:
                report_path.unlink()
                deleted_count += 1
                logger.debug(f"Deleted old report: {report_path}")
            except Exception as e:
                logger.warning(f"Failed to delete report {report_path}: {e}")

        logger.info(f"Cleaned {deleted_count} old reports, kept {keep_count}")
        return deleted_count

    def get_stats(self) -> dict:
        """
        获取目录统计信息

        Returns:
            统计信息字典
        """
        return {
            "base_dir": str(self.base_dir),
            "run_dir": str(self.run_dir),
            "cache_count": len(self.list_caches()),
            "dump_count": len(self.list_dumps()),
            "report_count": len(self.list_reports()),
        }

    def __repr__(self) -> str:
        stats = self.get_stats()
        return (
            f"MidsceneRunManager(run_dir={stats['run_dir']}, "
            f"reports={stats['report_count']}, "
            f"caches={stats['cache_count']})"
        )


# 全局单例（可选使用）
_default_manager: Optional[MidsceneRunManager] = None


def get_default_run_manager(base_dir: Optional[str] = None) -> MidsceneRunManager:
    """
    获取默认的目录管理器实例

    Args:
        base_dir: 基础目录路径

    Returns:
        MidsceneRunManager 实例
    """
    global _default_manager

    if _default_manager is None or (base_dir and str(_default_manager.base_dir) != base_dir):
        _default_manager = MidsceneRunManager(base_dir)

    return _default_manager


__all__ = [
    "MidsceneRunManager",
    "get_default_run_manager",
]
