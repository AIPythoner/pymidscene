from __future__ import annotations

import asyncio
from typing import Any, cast

from pymidscene.web_integration.playwright.agent import PlaywrightAgent
from pymidscene.web_integration.playwright.page import WebPage


class _FakeAsyncPage:
    def __init__(self) -> None:
        self.wait_for_selector_calls: list[dict[str, Any]] = []
        self.wait_for_load_state_calls: list[dict[str, Any]] = []

    async def wait_for_selector(self, selector: str, timeout: int) -> None:
        self.wait_for_selector_calls.append({"selector": selector, "timeout": timeout})

    async def wait_for_load_state(self, state: str, timeout: int) -> None:
        self.wait_for_load_state_calls.append({"state": state, "timeout": timeout})


class _FakeWrappedWebPage:
    def __init__(self, page: Any, **kwargs: Any) -> None:
        self.page = page
        self.kwargs = kwargs
        self.wait_calls: list[int] = []

    async def wait_for_network_idle(self, timeout: int | None = None) -> None:
        self.wait_calls.append(1000 if timeout is None else timeout)


class _FakeAgent:
    def __init__(self, interface: Any, **kwargs: Any) -> None:
        self.interface = interface
        self.kwargs = kwargs
        self.session_recorder = None
        self.ai_query_calls: list[tuple[Any, bool]] = []
        self.ai_assert_calls: list[tuple[str, str]] = []

    def finish(self) -> str:
        return "fake-report.html"

    def save_report(self) -> str:
        return "fake-report.html"

    def get_report_dir(self) -> str:
        return "fake-report-dir"

    def get_cache_stats(self) -> dict[str, int]:
        return {"hits": 0}

    async def ai_query(self, data_schema: Any, use_cache: bool = True) -> dict[str, Any]:
        self.ai_query_calls.append((data_schema, use_cache))
        return {"ok": True}

    async def ai_assert(self, assertion: str, message: str = "") -> bool:
        self.ai_assert_calls.append((assertion, message))
        return True


def test_web_page_constructor_preserves_zero_timeouts() -> None:
    page = _FakeAsyncPage()
    web_page = WebPage(
        cast(Any, page),
        wait_for_navigation_timeout=0,
        wait_for_network_idle_timeout=0,
    )

    assert web_page.wait_for_navigation_timeout == 0
    assert web_page.wait_for_network_idle_timeout == 0


def test_wait_for_navigation_skips_when_zero_timeout_is_explicit() -> None:
    page = _FakeAsyncPage()
    web_page = WebPage(cast(Any, page), wait_for_navigation_timeout=5000)

    asyncio.run(web_page.wait_for_navigation(timeout=0))

    assert page.wait_for_selector_calls == []


def test_wait_for_network_idle_skips_when_zero_timeout_is_explicit() -> None:
    page = _FakeAsyncPage()
    web_page = WebPage(cast(Any, page), wait_for_network_idle_timeout=5000)

    asyncio.run(web_page.wait_for_network_idle(timeout=0))

    assert page.wait_for_load_state_calls == []


def test_wait_for_network_idle_uses_zero_from_constructor() -> None:
    page = _FakeAsyncPage()
    web_page = WebPage(cast(Any, page), wait_for_network_idle_timeout=0)

    asyncio.run(web_page.wait_for_network_idle())

    assert page.wait_for_load_state_calls == []


def test_playwright_agent_wait_for_network_idle_passthrough(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "pymidscene.web_integration.playwright.agent.WebPage",
        _FakeWrappedWebPage,
    )
    monkeypatch.setattr(
        "pymidscene.web_integration.playwright.agent.Agent",
        _FakeAgent,
    )

    fake_page = object()
    agent = PlaywrightAgent(fake_page)

    asyncio.run(agent.wait_for_network_idle(250))

    assert isinstance(agent.interface, _FakeWrappedWebPage)
    assert agent.interface.wait_calls == [250]


def test_playwright_agent_ai_query_passes_use_cache(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "pymidscene.web_integration.playwright.agent.WebPage",
        _FakeWrappedWebPage,
    )
    monkeypatch.setattr(
        "pymidscene.web_integration.playwright.agent.Agent",
        _FakeAgent,
    )

    agent = PlaywrightAgent(object())
    result = asyncio.run(agent.ai_query({"title": "page title"}, use_cache=False))

    assert result == {"ok": True}
    fake_agent = cast(_FakeAgent, agent.agent)
    assert fake_agent.ai_query_calls == [({"title": "page title"}, False)]


def test_playwright_agent_ai_assert_normalizes_none_message(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "pymidscene.web_integration.playwright.agent.WebPage",
        _FakeWrappedWebPage,
    )
    monkeypatch.setattr(
        "pymidscene.web_integration.playwright.agent.Agent",
        _FakeAgent,
    )

    agent = PlaywrightAgent(object())
    result = asyncio.run(agent.ai_assert("page is visible", None))

    assert result is True
    fake_agent = cast(_FakeAgent, agent.agent)
    assert fake_agent.ai_assert_calls == [("page is visible", "")]
