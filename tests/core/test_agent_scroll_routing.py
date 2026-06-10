"""
core Agent.ai_scroll 的接口路由测试.

回归背景: 旧实现对 scrollTo*/带定位元素的 singleAction 一律走
`evaluate_javascript`, 而 Android/iOS 设备不认识这些脚本 → 静默 no-op.
现在应优先用原生 `scroll_until_*` / `scroll(start_point=...)`.
"""

from __future__ import annotations

import pytest

from pymidscene.core.agent.agent import Agent
from pymidscene.shared.types import LocateResultElement


class FakeMobileInterface:
    """Android/iOS 形态: 原生 scroll_until_* 与 scroll(start_point)."""

    def __init__(self):
        self.calls: list[tuple] = []

    async def scroll(self, direction, distance=None, start_point=None):
        self.calls.append(("scroll", direction, distance, start_point))

    async def scroll_until_top(self, start_point=None):
        self.calls.append(("scroll_until_top", start_point))

    async def scroll_until_bottom(self, start_point=None):
        self.calls.append(("scroll_until_bottom", start_point))

    async def scroll_until_left(self, start_point=None):
        self.calls.append(("scroll_until_left", start_point))

    async def scroll_until_right(self, start_point=None):
        self.calls.append(("scroll_until_right", start_point))

    async def evaluate_javascript(self, script):
        self.calls.append(("evaluate_javascript", script))


class FakeWebInterface:
    """Playwright 形态: scroll(starting_point=dict) + evaluate_javascript."""

    def __init__(self):
        self.calls: list[tuple] = []

    async def scroll(self, direction, distance=None, starting_point=None):
        self.calls.append(("scroll", direction, distance, starting_point))

    async def evaluate_javascript(self, script):
        self.calls.append(("evaluate_javascript", script))


def make_agent(interface) -> Agent:
    """绕过 Agent.__init__ (需要模型配置), 只装上 ai_scroll 用到的属性."""
    agent = object.__new__(Agent)
    agent.interface = interface
    agent.session_recorder = None
    return agent


def install_fake_locate(agent: Agent, center: tuple[float, float]) -> None:
    async def _locate(prompt: str):
        return LocateResultElement(
            description=prompt,
            center=center,
            rect={"left": 0, "top": 0, "width": 10, "height": 10, "zoom": None},
        )

    agent.ai_locate = _locate  # type: ignore[method-assign]


@pytest.mark.asyncio
class TestMobileRouting:
    @pytest.mark.parametrize(
        "scroll_type,expected",
        [
            ("scrollToTop", "scroll_until_top"),
            ("scrollToBottom", "scroll_until_bottom"),
            ("scrollToLeft", "scroll_until_left"),
            ("scrollToRight", "scroll_until_right"),
        ],
    )
    async def test_scroll_to_uses_native_method(self, scroll_type, expected):
        iface = FakeMobileInterface()
        agent = make_agent(iface)
        assert await agent.ai_scroll(scroll_type=scroll_type) is True
        names = [c[0] for c in iface.calls]
        assert expected in names
        assert "evaluate_javascript" not in names

    async def test_scroll_to_passes_located_start_point(self):
        iface = FakeMobileInterface()
        agent = make_agent(iface)
        install_fake_locate(agent, (120.0, 240.0))
        await agent.ai_scroll(scroll_type="scrollToBottom", locate_prompt="列表")
        call = next(c for c in iface.calls if c[0] == "scroll_until_bottom")
        assert call[1] == (120.0, 240.0)

    async def test_single_action_with_locate_uses_native_start_point(self):
        iface = FakeMobileInterface()
        agent = make_agent(iface)
        install_fake_locate(agent, (100.0, 200.0))
        await agent.ai_scroll("down", 300, "singleAction", "评论区")
        call = next(c for c in iface.calls if c[0] == "scroll")
        assert call[1:] == ("down", 300, (100.0, 200.0))
        assert not any(c[0] == "evaluate_javascript" for c in iface.calls)


@pytest.mark.asyncio
class TestWebRouting:
    async def test_scroll_to_top_falls_back_to_js(self):
        iface = FakeWebInterface()
        agent = make_agent(iface)
        await agent.ai_scroll(scroll_type="scrollToTop")
        call = next(c for c in iface.calls if c[0] == "evaluate_javascript")
        assert "scrollTo" in call[1]

    async def test_single_action_with_locate_uses_starting_point_kwarg(self):
        iface = FakeWebInterface()
        agent = make_agent(iface)
        install_fake_locate(agent, (50.0, 60.0))
        await agent.ai_scroll("down", 200, "singleAction", "侧边栏")
        call = next(c for c in iface.calls if c[0] == "scroll")
        assert call[1:] == ("down", 200, {"x": 50.0, "y": 60.0})

    async def test_single_action_without_locate_plain_scroll(self):
        iface = FakeWebInterface()
        agent = make_agent(iface)
        assert await agent.ai_scroll("up", 100) is True
        assert iface.calls == [("scroll", "up", 100, None)]
