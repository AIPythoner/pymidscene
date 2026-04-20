"""
任务缓存系统 - 对应 packages/core/src/agent/task-cache.ts

提供基于 YAML 的缓存系统，用于缓存 AI 的规划和定位结果。
"""

from typing import Optional, Dict, Any, List, Callable, Literal, Set
from dataclasses import dataclass, field
from pathlib import Path
import hashlib
import os
import yaml
import json

from ...shared.logger import logger
from ...shared.utils import calculate_hash


# 与 JS task-cache.ts:49 对齐 —— JS 会拒绝低于此版本的缓存记录.
# 写入时以此为下限,使 Python 产出的缓存可以被 JS 读取.
_JS_LOWEST_SUPPORTED_VERSION = "0.17.0"


def _sha256_hex(text: str) -> str:
    """sha256 摘要 —— 与 JS `generateHashId` 对齐的 hash 算法."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _get_cache_max_filename_length() -> int:
    """读取 MIDSCENE_CACHE_MAX_FILENAME_LENGTH,失败回落到 200 (与 JS 对齐)."""
    raw = os.environ.get("MIDSCENE_CACHE_MAX_FILENAME_LENGTH")
    if raw:
        try:
            val = int(raw)
            if val > 0:
                return val
        except (TypeError, ValueError):
            pass
    return 200


def _get_default_cache_dir() -> str:
    """读取 MIDSCENE_RUN_DIR,失败回落到 ./midscene_run (与 JS 对齐)."""
    run_dir = os.environ.get("MIDSCENE_RUN_DIR") or "./midscene_run"
    return os.path.join(run_dir, "cache")


def _resolve_midscene_version() -> str:
    """
    Resolve cache file's `midsceneVersion` to a value JS readers will accept.

    JS task-cache.ts:242-249 rejects anything below `0.16.10`. pymidscene's
    own package version is orthogonal (currently 0.1.x), so writing it raw
    would make every Python-produced cache invalid to JS. We floor to
    `_JS_LOWEST_SUPPORTED_VERSION` to preserve interoperability.
    """
    return _JS_LOWEST_SUPPORTED_VERSION


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
    # 写入时使用的 midsceneVersion,需保证 >= JS 最低支持版本 (0.16.10)
    MIDSCENE_VERSION = _resolve_midscene_version()

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

        # 限制文件名长度 (MIDSCENE_CACHE_MAX_FILENAME_LENGTH 与 JS 对齐)
        max_filename_length = _get_cache_max_filename_length()
        if len(safe_cache_id.encode('utf-8')) > max_filename_length:
            prefix = safe_cache_id[:32]
            # 与 JS `generateHashId` 对齐 —— 使用 sha256 前 8 位以保证跨语言 hash 一致
            hash_suffix = _sha256_hex(safe_cache_id)[:8]
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
                # 优先读 MIDSCENE_RUN_DIR,否则 ./midscene_run/cache (与 JS 对齐)
                cache_dir = _get_default_cache_dir()
            cache_dir_path = Path(cache_dir)
            cache_dir_path.mkdir(parents=True, exist_ok=True)
            self.cache_file_path = cache_dir_path / f"{self.cache_id}{self.CACHE_FILE_EXT}"

        # 加载或初始化缓存.
        # - read-only / read-write:载入已有文件,`match_cache` 能从中匹配
        # - write-only:不载入(匹配逻辑也不会拿到旧记录,`is_cache_result_used=False`),
        #   但 `append_cache → _flush_cache_to_file` 会在写入时读回原文件再 merge,
        #   因此旧记录不会被覆盖丢失.这与 JS `updateOrAppendCacheRecord` 对齐.
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
                    # 兼容 JS 旧版格式: 顶层 `xpaths` 自动迁移到 `cache.xpaths`
                    # 对应 JS task-cache.ts:138-146
                    cache_blob = item.get("cache")
                    legacy_xpaths = item.get("xpaths")
                    if legacy_xpaths and not cache_blob:
                        cache_blob = {"xpaths": legacy_xpaths}
                        logger.debug(
                            f"Migrated legacy locate xpaths for '{item.get('prompt')}'"
                        )
                    cache_content.caches.append(LocateCache(
                        type="locate",
                        prompt=item.get("prompt", ""),
                        cache=cache_blob,
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

        # write-only 模式:flush 前先从磁盘读回旧记录,和内存里新增的合并后再写.
        # 对齐 JS `updateOrAppendCacheRecord` —— 保证 write-only 不会把别的进程或
        # 上一轮写的旧记录覆盖丢失.
        merged_records: list[PlanningCache | LocateCache] = []
        if self.write_only_mode and self.cache_file_path.exists():
            existing = self._load_cache_from_file()
            if existing and existing.caches:
                merged_records.extend(existing.caches)
        merged_records.extend(self.cache.caches)

        # 转换为可序列化的字典(与 JS 版本对齐:midsceneVersion)
        data = {
            "midsceneVersion": self.cache.midscene_version,
            "cacheId": self.cache.cache_id,
            "caches": []
        }

        for cache_item in merged_records:
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
