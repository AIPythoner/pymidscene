"""
测试缓存系统
"""

import pytest
from pathlib import Path
import tempfile
import shutil

from pymidscene.core.agent.task_cache import (
    TaskCache,
    PlanningCache,
    LocateCache,
)


@pytest.fixture
def temp_cache_dir():
    """创建临时缓存目录"""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir)


def test_task_cache_initialization(temp_cache_dir):
    """测试缓存初始化"""
    cache = TaskCache(
        cache_id="test_cache",
        cache_dir=temp_cache_dir
    )

    assert cache.cache_id == "test_cache"
    assert cache.is_cache_result_used is True
    assert len(cache.cache.caches) == 0
    assert cache.read_only_mode is False
    assert cache.write_only_mode is False


def test_task_cache_sanitize_cache_id(temp_cache_dir):
    """测试缓存 ID 清理"""
    cache = TaskCache(
        cache_id="test/cache:with<illegal>chars",
        cache_dir=temp_cache_dir
    )

    # 非法字符应该被替换
    assert "/" not in cache.cache_id
    assert ":" not in cache.cache_id
    assert "<" not in cache.cache_id
    assert ">" not in cache.cache_id


def test_append_planning_cache(temp_cache_dir):
    """测试添加规划缓存"""
    cache = TaskCache(
        cache_id="test_plan_cache",
        cache_dir=temp_cache_dir
    )

    # 添加规划缓存
    plan_cache = PlanningCache(
        type="plan",
        prompt="搜索 Python 教程",
        yaml_workflow="- type: Tap\n  param:\n    prompt: 搜索框"
    )

    cache.append_cache(plan_cache)

    # 验证缓存已添加
    assert len(cache.cache.caches) == 1
    assert cache.cache.caches[0].type == "plan"
    assert cache.cache.caches[0].prompt == "搜索 Python 教程"


def test_append_locate_cache(temp_cache_dir):
    """测试添加定位缓存"""
    cache = TaskCache(
        cache_id="test_locate_cache",
        cache_dir=temp_cache_dir
    )

    # 添加定位缓存
    locate_cache = LocateCache(
        type="locate",
        prompt="登录按钮",
        cache={"xpath": "//button[@id='login']"}
    )

    cache.append_cache(locate_cache)

    # 验证缓存已添加
    assert len(cache.cache.caches) == 1
    assert cache.cache.caches[0].type == "locate"
    assert cache.cache.caches[0].prompt == "登录按钮"


def test_match_plan_cache(temp_cache_dir):
    """测试匹配规划缓存"""
    cache = TaskCache(
        cache_id="test_match_plan",
        cache_dir=temp_cache_dir
    )

    # 添加缓存
    plan_cache = PlanningCache(
        type="plan",
        prompt="搜索 Python",
        yaml_workflow="- type: Tap"
    )
    cache.append_cache(plan_cache)

    # 重新加载缓存
    cache2 = TaskCache(
        cache_id="test_match_plan",
        cache_dir=temp_cache_dir,
        is_cache_result_used=True
    )

    # 匹配缓存
    result = cache2.match_plan_cache("搜索 Python")

    assert result is not None
    assert result.cache_content.type == "plan"
    assert result.cache_content.prompt == "搜索 Python"


def test_match_locate_cache(temp_cache_dir):
    """测试匹配定位缓存"""
    cache = TaskCache(
        cache_id="test_match_locate",
        cache_dir=temp_cache_dir
    )

    # 添加缓存
    locate_cache = LocateCache(
        type="locate",
        prompt="登录按钮",
        cache={"xpath": "//button[@id='login']"}
    )
    cache.append_cache(locate_cache)

    # 重新加载缓存
    cache2 = TaskCache(
        cache_id="test_match_locate",
        cache_dir=temp_cache_dir,
        is_cache_result_used=True
    )

    # 匹配缓存
    result = cache2.match_locate_cache("登录按钮")

    assert result is not None
    assert result.cache_content.type == "locate"
    assert result.cache_content.prompt == "登录按钮"
    assert result.cache_content.cache == {"xpath": "//button[@id='login']"}


def test_no_match_cache(temp_cache_dir):
    """测试不匹配的缓存"""
    cache = TaskCache(
        cache_id="test_no_match",
        cache_dir=temp_cache_dir,
        is_cache_result_used=True
    )

    # 尝试匹配不存在的缓存
    result = cache.match_plan_cache("不存在的 prompt")

    assert result is None


def test_read_only_mode(temp_cache_dir):
    """测试只读模式"""
    # 先创建一个缓存
    cache = TaskCache(
        cache_id="test_readonly",
        cache_dir=temp_cache_dir
    )
    cache.append_cache(PlanningCache(
        type="plan",
        prompt="测试",
        yaml_workflow="test"
    ))

    # 以只读模式打开
    readonly_cache = TaskCache(
        cache_id="test_readonly",
        cache_dir=temp_cache_dir,
        strategy="read-only"
    )

    assert readonly_cache.read_only_mode is True
    assert len(readonly_cache.cache.caches) == 1

    # 添加新缓存（应该只在内存中）
    readonly_cache.append_cache(PlanningCache(
        type="plan",
        prompt="新缓存",
        yaml_workflow="new"
    ))

    # 重新加载，新缓存不应该被保存
    cache2 = TaskCache(
        cache_id="test_readonly",
        cache_dir=temp_cache_dir
    )
    assert len(cache2.cache.caches) == 1  # 只有原来的一个


def test_write_only_mode(temp_cache_dir):
    """测试只写模式"""
    # 先创建一个缓存
    cache = TaskCache(
        cache_id="test_writeonly",
        cache_dir=temp_cache_dir
    )
    cache.append_cache(PlanningCache(
        type="plan",
        prompt="旧缓存",
        yaml_workflow="old"
    ))

    # 以只写模式打开
    writeonly_cache = TaskCache(
        cache_id="test_writeonly",
        cache_dir=temp_cache_dir,
        strategy="write-only"
    )

    assert writeonly_cache.write_only_mode is True
    assert writeonly_cache.is_cache_result_used is False
    assert len(writeonly_cache.cache.caches) == 0  # 不加载已有缓存

    # 添加新缓存
    writeonly_cache.append_cache(PlanningCache(
        type="plan",
        prompt="新缓存",
        yaml_workflow="new"
    ))

    # 重新加载，应该有两个缓存
    cache2 = TaskCache(
        cache_id="test_writeonly",
        cache_dir=temp_cache_dir
    )
    assert len(cache2.cache.caches) == 2


def test_cache_stats(temp_cache_dir):
    """测试缓存统计"""
    cache = TaskCache(
        cache_id="test_stats",
        cache_dir=temp_cache_dir
    )

    cache.append_cache(PlanningCache(
        type="plan",
        prompt="测试1",
        yaml_workflow="test1"
    ))
    cache.append_cache(PlanningCache(
        type="plan",
        prompt="测试2",
        yaml_workflow="test2"
    ))

    stats = cache.get_stats()

    assert stats["cache_id"] == "test_stats"
    assert stats["total_records"] == 2
    assert stats["strategy"] == "read-write"


def test_cache_reuse_prevention(temp_cache_dir):
    """测试防止重复使用同一缓存"""
    cache = TaskCache(
        cache_id="test_reuse",
        cache_dir=temp_cache_dir
    )

    # 添加相同 prompt 的缓存
    cache.append_cache(PlanningCache(
        type="plan",
        prompt="相同 prompt",
        yaml_workflow="第一次"
    ))
    cache.append_cache(PlanningCache(
        type="plan",
        prompt="相同 prompt",
        yaml_workflow="第二次"
    ))

    # 重新加载
    cache2 = TaskCache(
        cache_id="test_reuse",
        cache_dir=temp_cache_dir,
        is_cache_result_used=True
    )

    # 第一次匹配
    result1 = cache2.match_plan_cache("相同 prompt")
    assert result1 is not None
    assert result1.cache_content.yaml_workflow == "第一次"

    # 第二次匹配应该得到不同的缓存
    result2 = cache2.match_plan_cache("相同 prompt")
    assert result2 is not None
    assert result2.cache_content.yaml_workflow == "第二次"

    # 第三次匹配应该没有结果
    result3 = cache2.match_plan_cache("相同 prompt")
    assert result3 is None
