"""
测试工具函数
"""

import pytest
from pymidscene.shared.utils import (
    calculate_hash,
    safe_parse_json,
    extract_json_from_code_block,
    get_screenshot_scale,
    format_bbox,
    calculate_center,
)


def test_calculate_hash():
    """测试哈希计算"""
    text = "hello world"
    hash_value = calculate_hash(text)
    assert isinstance(hash_value, str)
    assert len(hash_value) == 32  # MD5 哈希长度

    # 相同输入应该产生相同哈希
    assert calculate_hash(text) == hash_value


def test_safe_parse_json():
    """测试安全 JSON 解析"""
    # 有效 JSON
    result = safe_parse_json('{"key": "value"}')
    assert result == {"key": "value"}

    # 无效 JSON
    result = safe_parse_json("invalid json")
    assert result is None


def test_extract_json_from_code_block():
    """测试从代码块提取 JSON"""
    # Markdown 代码块
    text = """```json
{"key": "value"}
```"""
    result = extract_json_from_code_block(text)
    assert result.strip() == '{"key": "value"}'

    # 普通代码块
    text = """```
{"key": "value"}
```"""
    result = extract_json_from_code_block(text)
    assert result.strip() == '{"key": "value"}'


def test_get_screenshot_scale():
    """测试截图缩放比例计算"""
    scale = get_screenshot_scale(1920.0, 1920.0)
    assert scale == 1.0

    scale = get_screenshot_scale(1920.0, 960.0)
    assert scale == 2.0

    scale = get_screenshot_scale(960.0, 1920.0)
    assert scale == 0.5


def test_format_bbox():
    """测试 bbox 格式化"""
    bbox = (10, 20, 100, 50)
    rect = format_bbox(bbox)

    assert rect["left"] == 10.0
    assert rect["top"] == 20.0
    assert rect["width"] == 100.0
    assert rect["height"] == 50.0


def test_calculate_center():
    """测试中心点计算"""
    rect = {
        "left": 10.0,
        "top": 20.0,
        "width": 100.0,
        "height": 50.0,
    }
    center = calculate_center(rect)

    assert center == (60.0, 45.0)  # (10 + 100/2, 20 + 50/2)
