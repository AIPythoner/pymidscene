"""
任务缓存系统 - 对应 packages/core/src/agent/task-cache.ts

提供基于 YAML 的缓存系统，用于缓存 AI 的规划和定位结果。
"""

from typing import Optional, Dict, Any, List, Callable, Literal, Set
from dataclasses import dataclass, field
from pathlib import Path
import yaml
import json

from ...shared.logger import logger
from ...shared.utils import calculate_hash


# 缓存类型定义
CacheType = Literal["plan", "locate"]
CacheStrategy = Literal["read-only", "read-write", "write-only"]


@dataclass
class PlanningCache:
    """规划缓存"""
    type: Literal["plan"] = "plan"
    prompt: str = ""
    yaml_workflow: str = ""


@dataclass
class LocateCache:
    """定位缓存"""
    type: Literal["locate"] = "locate"
    prompt: str | Dict[str, Any] = ""
    cache: Optional[Dict[str, Any]] = None


@dataclass
class MatchCacheResult:
    """缓存匹配结果"""
    cache_content: PlanningCache | LocateCache
    update_fn: Callable[[PlanningCache | LocateCache], None]


@dataclass
class CacheFileContent:
    """缓存文件内容"""
    midscene_version: str  # 与 JS 版本对齐：midsceneVersion
    cache_id: str
    caches: List[PlanningCache | LocateCache] = field(default_factory=list)


class TaskCache:
    """任务缓存管理器"""

    CACHE_FILE_EXT = ".cache.yaml"
    DEFAULT_CACHE_MAX_FILENAME_LENGTH = 200
    MIDSCENE_VERSION = "1.0.0"  # 与 JS 版本对齐

    def __init__(
        self,
        cache_id: str,
        is_cache_result_used: bool = True,
        cache_file_path: Optional[str] = None,
        strategy: CacheStrategy = "read-write",
        cache_dir: Optional[str] = None,
    ):
        """
        初始化任务缓存

        Args:
            cache_id: 缓存 ID（通常是测试名称）
            is_cache_result_used: 是否使用缓存结果
            cache_file_path: 缓存文件路径（可选）
            strategy: 缓存策略（read-only, read-write, write-only）
            cache_dir: 缓存目录（可选）
        """
        if not cache_id:
            raise ValueError("cache_id is required")

        # 清理缓存 ID（移除非法字符）
        safe_cache_id = self._sanitize_cache_id(cache_id)

        # 限制文件名长度
        if len(safe_cache_id.encode('utf-8')) > self.DEFAULT_CACHE_MAX_FILENAME_LENGTH:
            prefix = safe_cache_id[:32]
            hash_suffix = calculate_hash(safe_cache_id)[:8]
            safe_cache_id = f"{prefix}-{hash_suffix}"

        self.cache_id = safe_cache_id

        # 设置缓存策略
        self.read_only_mode = strategy == "read-only"
        self.write_only_mode = strategy == "write-only"

        if self.read_only_mode and self.write_only_mode:
            raise ValueError("TaskCache cannot be both read-only and write-only")

        # write-only 模式下不使用缓存结果
        self.is_cache_result_used = False if self.write_only_mode else is_cache_result_used

        # 确定缓存文件路径（与 JS 版本对齐：midscene_run/cache/）
        if cache_file_path:
            self.cache_file_path = Path(cache_file_path)
        else:
            if cache_dir is None:
                # 与 JS 版本保持一致，使用 midscene_run/cache 目录
                cache_dir = "./midscene_run/cache"
            cache_dir_path = Path(cache_dir)
            cache_dir_path.mkdir(parents=True, exist_ok=True)
            self.cache_file_path = cache_dir_path / f"{self.cache_id}{self.CACHE_FILE_EXT}"

        # 加载或初始化缓存
        cache_content: Optional[CacheFileContent] = None
        if not self.write_only_mode:
            cache_content = self._load_cache_from_file()

        if cache_content is None:
            cache_content = CacheFileContent(
                midscene_version=self.MIDSCENE_VERSION,
                cache_id=self.cache_id,
                caches=[]
            )

        self.cache = cache_content
        self.cache_original_length = len(self.cache.caches) if self.is_cache_result_used else 0

        # 跟踪已匹配的缓存记录
        self.matched_cache_indices: Set[str] = set()

        logger.debug(
            f"TaskCache initialized: id={self.cache_id}, "
            f"strategy={strategy}, "
            f"records={len(self.cache.caches)}, "
            f"path={self.cache_file_path}"
        )

    def _sanitize_cache_id(self, cache_id: str) -> str:
        """清理缓存 ID，移除非法字符"""
        # 替换非法路径字符
        illegal_chars = '<>:"|?*\\/\n\r\t'
        safe_id = cache_id
        for char in illegal_chars:
            safe_id = safe_id.replace(char, "_")
        # 替换空格
        safe_id = safe_id.replace(" ", "-")
        return safe_id

    def match_cache(
        self,
        prompt: str | Dict[str, Any],
        cache_type: CacheType
    ) -> Optional[MatchCacheResult]:
        """
        匹配缓存

        Args:
            prompt: Prompt（字符串或字典）
            cache_type: 缓存类型（plan 或 locate）

        Returns:
            匹配结果或 None
        """
        if not self.is_cache_result_used:
            return None

        # 将 prompt 转换为字符串用于比较
        prompt_str = prompt if isinstance(prompt, str) else json.dumps(prompt, sort_keys=True)

        # 查找第一个未使用的匹配缓存
        for i in range(self.cache_original_length):
            item = self.cache.caches[i]
            key = f"{cache_type}:{prompt_str}:{i}"

            # 检查类型和 prompt 是否匹配，且未被使用
            item_prompt_str = (
                item.prompt if isinstance(item.prompt, str)
                else json.dumps(item.prompt, sort_keys=True)
            )

            if (
                item.type == cache_type
                and item_prompt_str == prompt_str
                and key not in self.matched_cache_indices
            ):
                # 标记为已使用
                self.matched_cache_indices.add(key)

                logger.debug(
                    f"Cache found: type={cache_type}, "
                    f"prompt={prompt_str[:50]}..., "
                    f"index={i}"
                )

                # 创建更新函数
                def update_fn(cache_item: PlanningCache | LocateCache) -> None:
                    """更新缓存项"""
                    logger.debug(
                        f"Updating cache: type={cache_type}, "
                        f"prompt={prompt_str[:50]}..., "
                        f"index={i}"
                    )

                    # 更新缓存内容
                    self.cache.caches[i] = cache_item

                    if self.read_only_mode:
                        logger.debug("Read-only mode: cache updated in memory only")
                        return

                    # 写入文件
                    self._flush_cache_to_file()

                return MatchCacheResult(
                    cache_content=item,
                    update_fn=update_fn
                )

        logger.debug(f"No cache found: type={cache_type}, prompt={prompt_str[:50]}...")
        return None

    def match_plan_cache(self, prompt: str) -> Optional[MatchCacheResult]:
        """匹配规划缓存"""
        return self.match_cache(prompt, "plan")

    def match_locate_cache(
        self,
        prompt: str | Dict[str, Any]
    ) -> Optional[MatchCacheResult]:
        """匹配定位缓存"""
        return self.match_cache(prompt, "locate")

    def append_cache(self, cache: PlanningCache | LocateCache) -> None:
        """
        添加新缓存

        Args:
            cache: 缓存项
        """
        logger.debug(f"Appending cache: type={cache.type}")
        self.cache.caches.append(cache)

        if self.read_only_mode:
            logger.debug("Read-only mode: cache appended to memory only")
            return

        self._flush_cache_to_file()

    def _load_cache_from_file(self) -> Optional[CacheFileContent]:
        """从文件加载缓存"""
        if not self.cache_file_path.exists():
            logger.debug(f"No cache file found: {self.cache_file_path}")
            return None

        try:
            with open(self.cache_file_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)

            if not data:
                return None

            # 转换为 CacheFileContent（兼容 JS 版本的 midsceneVersion 和旧版 pymidsceneVersion）
            cache_content = CacheFileContent(
                midscene_version=data.get("midsceneVersion", data.get("pymidsceneVersion", "0.0.0")),
                cache_id=data.get("cacheId", self.cache_id),
                caches=[]
            )

            # 解析缓存项
            for item in data.get("caches", []):
                if item.get("type") == "plan":
                    cache_content.caches.append(PlanningCache(
                        type="plan",
                        prompt=item.get("prompt", ""),
                        yaml_workflow=item.get("yamlWorkflow", "")
                    ))
                elif item.get("type") == "locate":
                    cache_content.caches.append(LocateCache(
                        type="locate",
                        prompt=item.get("prompt", ""),
                        cache=item.get("cache")
                    ))

            logger.info(
                f"Cache loaded: {self.cache_file_path}, "
                f"version={cache_content.midscene_version}, "
                f"records={len(cache_content.caches)}"
            )

            # 更新版本号
            cache_content.midscene_version = self.MIDSCENE_VERSION

            return cache_content

        except Exception as e:
            logger.error(f"Failed to load cache file: {self.cache_file_path}, error: {e}")
            return None

    def _flush_cache_to_file(self, clean_unused: bool = False) -> None:
        """
        将缓存写入文件

        Args:
            clean_unused: 是否清理未使用的缓存
        """
        if not self.cache_file_path:
            logger.debug("No cache file path, will not write cache")
            return

        # 清理未使用的缓存
        if clean_unused and self.is_cache_result_used:
            original_length = len(self.cache.caches)

            # 收集已使用的索引
            used_indices = set()
            for key in self.matched_cache_indices:
                # key 格式: "type:prompt:index"
                parts = key.split(":")
                try:
                    index = int(parts[-1])
                    used_indices.add(index)
                except (ValueError, IndexError):
                    pass

            # 过滤：保留已使用的缓存和新添加的缓存
            self.cache.caches = [
                cache for i, cache in enumerate(self.cache.caches)
                if i in used_indices or i >= self.cache_original_length
            ]

            cleaned_count = original_length - len(self.cache.caches)
            if cleaned_count > 0:
                logger.info(f"Cleaned {cleaned_count} unused cache records")

        # 确保目录存在
        self.cache_file_path.parent.mkdir(parents=True, exist_ok=True)

        # 转换为可序列化的字典（与 JS 版本对齐：midsceneVersion）
        data = {
            "midsceneVersion": self.cache.midscene_version,
            "cacheId": self.cache.cache_id,
            "caches": []
        }

        for cache_item in self.cache.caches:
            if isinstance(cache_item, PlanningCache):
                data["caches"].append({
                    "type": "plan",
                    "prompt": cache_item.prompt,
                    "yamlWorkflow": cache_item.yaml_workflow
                })
            elif isinstance(cache_item, LocateCache):
                data["caches"].append({
                    "type": "locate",
                    "prompt": cache_item.prompt,
                    "cache": cache_item.cache
                })

        # 写入 YAML 文件
        try:
            with open(self.cache_file_path, 'w', encoding='utf-8') as f:
                yaml.dump(
                    data,
                    f,
                    default_flow_style=False,
                    allow_unicode=True,
                    sort_keys=False
                )

            logger.debug(
                f"Cache flushed to file: {self.cache_file_path}, "
                f"records={len(self.cache.caches)}"
            )

        except Exception as e:
            logger.error(f"Failed to write cache file: {self.cache_file_path}, error: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        return {
            "cache_id": self.cache_id,
            "total_records": len(self.cache.caches),
            "original_records": self.cache_original_length,
            "matched_records": len(self.matched_cache_indices),
            "strategy": (
                "read-only" if self.read_only_mode
                else "write-only" if self.write_only_mode
                else "read-write"
            ),
            "cache_file": str(self.cache_file_path),
        }

    def __repr__(self) -> str:
        stats = self.get_stats()
        return (
            f"TaskCache(id={stats['cache_id']}, "
            f"records={stats['total_records']}, "
            f"matched={stats['matched_records']}, "
            f"strategy={stats['strategy']})"
        )


__all__ = [
    "TaskCache",
    "PlanningCache",
    "LocateCache",
    "MatchCacheResult",
    "CacheFileContent",
    "CacheType",
    "CacheStrategy",
]
