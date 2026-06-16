"""
deepThink 两段式 section-zoom 定位 + auto-glm locate(Batch B)的测试。

覆盖:几何/图像 helper(merge_rects / expand_search_area / crop_image_base64)、
ai_locate(deep_think=True) 的"section→裁剪→带偏移重定位→坐标映射回全图"流程、
默认路径(deep_think=False)不跑 section、auto-glm 点坐标定位分支。
"""

from __future__ import annotations

import base64
from io import BytesIO
from types import SimpleNamespace

import pytest
from PIL import Image

from pymidscene.core.agent.agent import Agent
from pymidscene.shared.utils import (
    crop_image_base64,
    expand_search_area,
    merge_rects,
)


def _white_png_b64(width: int, height: int) -> str:
    img = Image.new("RGB", (width, height), (255, 255, 255))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


# --- geometry / image helpers -----------------------------------------------

class TestGeometryHelpers:
    def test_merge_rects_bounding_box(self):
        m = merge_rects([
            {"left": 10, "top": 20, "width": 30, "height": 40},
            {"left": 5, "top": 50, "width": 10, "height": 10},
        ])
        assert m == {"left": 5, "top": 20, "width": 35, "height": 40}

    def test_expand_to_min_edge_and_clamp(self):
        e = expand_search_area(
            {"left": 800, "top": 800, "width": 40, "height": 30}, 2000, 2000, None
        )
        assert e["width"] >= 500 and e["height"] >= 500
        assert e["left"] >= 0 and e["top"] >= 0
        assert e["left"] + e["width"] <= 2000
        assert e["top"] + e["height"] <= 2000

    def test_qwen3vl_uses_1200_min_edge(self):
        e = expand_search_area(
            {"left": 100, "top": 100, "width": 50, "height": 50}, 4000, 4000,
            "qwen3-vl",
        )
        assert e["width"] >= 1200 and e["height"] >= 1200

    def test_expand_clamps_into_screen_when_near_edge(self):
        e = expand_search_area(
            {"left": 1900, "top": 1900, "width": 80, "height": 80}, 2000, 2000, None
        )
        assert e["left"] + e["width"] <= 2000
        assert e["top"] + e["height"] <= 2000

    def test_crop_returns_actual_dims(self):
        b64 = _white_png_b64(1000, 800)
        _, w, h = crop_image_base64(b64, 100, 50, 300, 200)
        assert (w, h) == (300, 200)

    def test_crop_pad_to_block_rounds_up_to_28(self):
        b64 = _white_png_b64(1000, 800)
        _, w, h = crop_image_base64(b64, 0, 0, 100, 100, pad_to_block=True)
        assert w % 28 == 0 and h % 28 == 0
        assert w >= 100 and h >= 100  # 112x112

    def test_crop_clamps_out_of_bounds(self):
        b64 = _white_png_b64(500, 500)
        _, w, h = crop_image_base64(b64, 400, 400, 300, 300)  # would overflow
        assert w == 100 and h == 100

    def test_crop_left_at_or_beyond_edge_does_not_crash(self):
        b64 = _white_png_b64(500, 500)
        # left==img_w 和 left>img_w 都不应崩,返回至少 1px 的合法裁剪
        for left in (500, 600):
            _, w, h = crop_image_base64(b64, left, 0, 100, 100)
            assert w >= 1 and h >= 1


# --- ai_locate deepThink / default / auto-glm via stubbed Agent --------------

def _make_locate_agent(model_family: str, responses: list):
    agent = object.__new__(Agent)
    agent.session_recorder = None
    agent.recorder = None
    agent.task_cache = None
    agent.interface = SimpleNamespace()
    state = {"i": 0, "calls": []}
    img_b64 = _white_png_b64(2000, 2000)

    async def _shot():
        return img_b64, {"width": 2000, "height": 2000, "dpr": 1}

    async def _call(messages, intent):
        state["calls"].append(messages)
        i = state["i"]
        state["i"] += 1
        return {"content": responses[i], "usage": None}

    agent._capture_ai_screenshot = _shot
    agent._call_ai_with_config_async = _call
    agent._get_model_config = lambda intent: SimpleNamespace(
        model_name="m", model_family=model_family
    )
    agent._resolve_model_family = lambda config: model_family
    return agent, state


@pytest.mark.asyncio
async def test_deepthink_maps_coords_back_to_full_image():
    # glm-4v: bbox 归一化 0-1000;section 在全图、element 在裁剪图,最终坐标应映射回全图
    section_resp = '{"bbox": [400, 400, 600, 600]}'
    element_resp = '{"bbox": [100, 100, 200, 200]}'
    agent, state = _make_locate_agent("glm-4v", [section_resp, element_resp])

    el = await agent.ai_locate("a dense list item", deep_think=True)
    assert state["i"] == 2  # 两次 AI 调用:section + element
    assert el is not None
    # section [400,400,600,600]/1000*2000 -> {800,800,w400,h400}
    #   expand -> {750,750,500,500} crop 500x500, offset (750,750)
    # element [100,100,200,200]/1000*500 -> px(50,50,100,100) +offset -> {800,800,50,50}
    cx, cy = el.center
    assert round(cx) == 825 and round(cy) == 825


@pytest.mark.asyncio
async def test_default_path_no_section_call():
    # 不开 deep_think:只有一次 AI 调用,坐标按全图算
    element_resp = '{"bbox": [100, 100, 200, 200]}'
    agent, state = _make_locate_agent("glm-4v", [element_resp])

    el = await agent.ai_locate("a button", deep_think=False)
    assert state["i"] == 1  # 仅 element,一次调用(没有 section 段)
    assert el is not None
    # [100,100,200,200]/1000*2000 -> {200,200,w200,h200}, center (300,300)
    cx, cy = el.center
    assert round(cx) == 300 and round(cy) == 300


@pytest.mark.asyncio
async def test_deepthink_disabled_for_auto_glm_family():
    # auto-glm 被 guard 禁用 section;走 auto-glm 点坐标定位分支,单次调用
    auto_glm_resp = '<think>found</think>\ndo(action="Tap", element=[500, 500])'
    agent, state = _make_locate_agent("auto-glm", [auto_glm_resp])

    el = await agent.ai_locate("the button", deep_think=True)
    assert state["i"] == 1  # 没有 section 段(auto-glm guard)
    assert el is not None
    # point 500/1000*2000 = 1000 -> 10px bbox around -> center (1000,1000)
    cx, cy = el.center
    assert round(cx) == 1000 and round(cy) == 1000


@pytest.mark.asyncio
async def test_deepthink_falls_back_to_full_image_when_section_not_found():
    # section 段返回无 bbox -> 回退全图定位(仍是两次调用,但 element 用全图坐标)
    section_resp = '{"bbox": null, "error": "no section"}'
    element_resp = '{"bbox": [100, 100, 200, 200]}'
    agent, state = _make_locate_agent("glm-4v", [section_resp, element_resp])

    el = await agent.ai_locate("x", deep_think=True)
    assert state["i"] == 2
    assert el is not None
    cx, cy = el.center
    assert round(cx) == 300 and round(cy) == 300  # 全图坐标,未裁剪
