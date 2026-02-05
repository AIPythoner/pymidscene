"""
测试共享类型定义
"""

import pytest
from pymidscene.shared.types import Point, Size, Rect, LocateResultElement


def test_point_type():
    """测试 Point 类型"""
    point: Point = {"left": 10.0, "top": 20.0}
    assert point["left"] == 10.0
    assert point["top"] == 20.0


def test_size_type():
    """测试 Size 类型"""
    size: Size = {"width": 1920.0, "height": 1080.0, "dpr": None}
    assert size["width"] == 1920.0
    assert size["height"] == 1080.0


def test_rect_type():
    """测试 Rect 类型"""
    rect: Rect = {
        "left": 10.0,
        "top": 20.0,
        "width": 100.0,
        "height": 50.0,
        "zoom": None
    }
    assert rect["left"] == 10.0
    assert rect["width"] == 100.0


def test_locate_result_element():
    """测试 LocateResultElement"""
    element = LocateResultElement(
        description="登录按钮",
        center=(100.0, 200.0),
        rect={
            "left": 50.0,
            "top": 175.0,
            "width": 100.0,
            "height": 50.0,
            "zoom": None
        }
    )
    assert element.description == "登录按钮"
    assert element.center == (100.0, 200.0)
    assert element.rect["width"] == 100.0
