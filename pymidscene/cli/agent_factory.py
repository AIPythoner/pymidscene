"""
目标块 -> Agent 构造 - 对齐 @midscene/cli/src/create-yaml-player.ts 的
``setupAgent`` 闭包。

按 ``web | android | ios | interface`` 检测目标并构造对应平台的 agent,返回
``SetupResult(agent, platform, teardown)``;``teardown`` 是一组在脚本跑完后
逆序执行的异步清理回调(关闭 context/浏览器、断开设备等)。
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from ..shared.logger import logger
from .yaml_script import MidsceneYamlScript, detect_target_type

TeardownFn = Callable[[], Awaitable[None]]

# 默认浏览器视口(对齐 JS launchPuppeteerPage 的 1440x768)。
_DEFAULT_VIEWPORT_WIDTH = 1440
_DEFAULT_VIEWPORT_HEIGHT = 768

# camelCase yaml key -> AndroidDeviceOpt 字段(snake_case)。
_ANDROID_OPT_MAP = {
    "adbPath": "android_adb_path",
    "androidAdbPath": "android_adb_path",
    "remoteAdbHost": "remote_adb_host",
    "remoteAdbPort": "remote_adb_port",
    "displayId": "display_id",
    "usePhysicalDisplayIdForDisplayLookup": "use_physical_display_id_for_display_lookup",
    "usePhysicalDisplayIdForScreenshot": "use_physical_display_id_for_screenshot",
    "screenshotResizeScale": "screenshot_resize_scale",
    "alwaysRefreshScreenInfo": "always_refresh_screen_info",
    "minScreenshotBufferSize": "min_screenshot_buffer_size",
    "autoDismissKeyboard": "auto_dismiss_keyboard",
    "keyboardDismissStrategy": "keyboard_dismiss_strategy",
    "imeStrategy": "ime_strategy",
}

_IOS_OPT_MAP = {
    "wdaHost": "wda_host",
    "wdaPort": "wda_port",
    "wdaBaseUrl": "wda_base_url",
    "wdaTimeout": "wda_timeout",
    "autoDismissKeyboard": "auto_dismiss_keyboard",
}


@dataclass
class SetupResult:
    """``setup_agent`` 的返回:agent 包装器 + 平台名 + 清理回调。"""

    agent: Any
    platform: str
    teardown: list[TeardownFn] = field(default_factory=list)


def _resolve_cache_id(script: MidsceneYamlScript, file_name: str) -> str | None:
    """对齐 JS processCacheConfig:cache 缺省=关;true=用文件名;dict 看 id。"""
    cache = script.agent.get("cache")
    if cache is False or cache is None:
        return None
    if cache is True:
        return file_name
    if isinstance(cache, dict):
        return cache.get("id", file_name)
    return None


def _agent_kwargs(
    script: MidsceneYamlScript, file_name: str, report_dir: str | None
) -> dict:
    kwargs: dict = {"cache_id": _resolve_cache_id(script, file_name)}
    if report_dir:
        kwargs["report_dir"] = report_dir
    return kwargs


def _map_opt(env: dict, key_map: dict) -> dict:
    out: dict = {}
    for camel_key, snake_key in key_map.items():
        if camel_key in env and env[camel_key] is not None:
            out[snake_key] = env[camel_key]
    return out


async def _setup_web(
    script: MidsceneYamlScript,
    file_name: str,
    headed: bool,
    keep_window: bool,
    shared_context: Any,
    report_dir: str | None,
) -> SetupResult:
    web = script.web or {}
    url = web.get("url")
    if not url:
        raise ValueError("web target requires a 'url' field")
    if web.get("serve"):
        logger.warning(
            "web 'serve' (local static server) is not supported by the Python "
            "CLI yet; ignoring and using the url as-is."
        )
    if web.get("bridgeMode"):
        raise ValueError(
            "web 'bridgeMode' is not supported by the Python CLI "
            "(requires the Chrome extension bridge)."
        )

    from playwright.async_api import async_playwright

    from ..web_integration.playwright.agent import PlaywrightAgent

    teardown: list[TeardownFn] = []

    # 共享模式:复用 batch 建好的同一个 context(共享 cookie/会话, 对齐 JS 的
    # browser.newPage() 同 browser 共享语义);非共享:本文件独占 pw+browser
    # +context, 结束后全部关闭。
    if shared_context is not None:
        context = shared_context
        own_context = False
        pw = None
        browser = None
    else:
        context_kwargs: dict = {}
        user_agent = web.get("userAgent")
        if user_agent:
            context_kwargs["user_agent"] = user_agent
        scale = web.get("viewportScale")
        if scale:
            context_kwargs["device_scale_factor"] = scale
        if web.get("acceptInsecureCerts"):
            context_kwargs["ignore_https_errors"] = True
        if headed:
            context_kwargs["no_viewport"] = True
        else:
            context_kwargs["viewport"] = {
                "width": int(web.get("viewportWidth") or _DEFAULT_VIEWPORT_WIDTH),
                "height": int(web.get("viewportHeight") or _DEFAULT_VIEWPORT_HEIGHT),
            }
        pw = await async_playwright().start()
        browser = await pw.chromium.launch(headless=not headed)
        context = await browser.new_context(**context_kwargs)
        own_context = True

    cookie_path = web.get("cookie")
    if cookie_path:
        # 不吞错(对齐 JS:cookie 读取/解析失败直接让 setup 失败, 而不是
        # 静默无 cookie 运行后在登录态断言处莫名失败)。
        with open(cookie_path, encoding="utf-8") as fh:
            cookies = json.load(fh)
        await context.add_cookies(cookies)

    page = await context.new_page()
    await page.goto(url)

    wait_idle = web.get("waitForNetworkIdle")
    if wait_idle is None or (
        isinstance(wait_idle, dict) and wait_idle.get("timeout", 1) != 0
    ):
        try:
            await page.wait_for_load_state("networkidle")
        except Exception as exc:  # noqa: BLE001
            cont = True
            if isinstance(wait_idle, dict):
                cont = wait_idle.get("continueOnNetworkIdleError", True)
            if not cont:
                raise
            logger.warning(f"waitForNetworkIdle: {exc} (continuing)")

    agent = PlaywrightAgent(page, **_agent_kwargs(script, file_name, report_dir))

    async def _teardown() -> None:
        if keep_window:
            return
        if own_context:
            for closer in (context.close, getattr(browser, "close", None),
                           getattr(pw, "stop", None)):
                if closer is None:
                    continue
                try:
                    await closer()
                except Exception:  # noqa: BLE001
                    pass
        else:
            # 共享 context:只关本文件的 page, context/browser 由 batch 收尾。
            try:
                await page.close()
            except Exception:  # noqa: BLE001
                pass

    teardown.append(_teardown)
    return SetupResult(agent=agent, platform="web", teardown=teardown)


async def _setup_android(
    script: MidsceneYamlScript, file_name: str, report_dir: str | None
) -> SetupResult:
    from ..android.device import AndroidDeviceOpt
    from ..android.utils import agent_from_adb_device

    android = script.android or {}
    opt = AndroidDeviceOpt(**_map_opt(android, _ANDROID_OPT_MAP))
    agent = await agent_from_adb_device(
        device_id=android.get("deviceId"),
        device_opt=opt,
        **_agent_kwargs(script, file_name, report_dir),
    )
    if android.get("launch"):
        await agent.launch(android["launch"])

    async def _teardown() -> None:
        try:
            await agent.device.destroy()
        except Exception:  # noqa: BLE001
            pass

    return SetupResult(agent=agent, platform="android", teardown=[_teardown])


async def _setup_ios(
    script: MidsceneYamlScript, file_name: str, report_dir: str | None
) -> SetupResult:
    from ..ios.device import IOSDeviceOpt
    from ..ios.utils import agent_from_webdriver_agent

    ios = script.ios or {}
    opt = IOSDeviceOpt(**_map_opt(ios, _IOS_OPT_MAP))
    agent = await agent_from_webdriver_agent(
        device_opt=opt, **_agent_kwargs(script, file_name, report_dir)
    )
    if ios.get("launch"):
        await agent.launch(ios["launch"])

    async def _teardown() -> None:
        try:
            await agent.device.destroy()
        except Exception:  # noqa: BLE001
            pass

    return SetupResult(agent=agent, platform="ios", teardown=[_teardown])


async def _setup_interface(
    script: MidsceneYamlScript, file_name: str, report_dir: str | None
) -> SetupResult:
    from ..core.agent.agent import Agent

    iface = script.interface or {}
    module_spec = iface.get("module")
    if not module_spec:
        raise ValueError("interface target requires a 'module' field")

    # 相对路径基于 cwd 解析(对齐 JS:相对/绝对 -> 基于 cwd)。
    if module_spec.startswith((".", os.sep)) or os.path.isabs(module_spec):
        path = os.path.join(os.getcwd(), module_spec)
        mod_name = os.path.splitext(os.path.basename(path))[0]
        spec = importlib.util.spec_from_file_location(mod_name, path)
        if spec is None or spec.loader is None:
            raise ValueError(f"Cannot import interface module from {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    else:
        module = importlib.import_module(module_spec)

    export = iface.get("export")
    device_cls = getattr(module, export) if export else getattr(
        module, "default", None
    )
    if device_cls is None:
        raise ValueError(
            f"interface module '{module_spec}' has no export "
            f"'{export or 'default'}'"
        )
    device = device_cls(**(iface.get("param") or {}))
    if hasattr(device, "connect"):
        await device.connect()
    agent = Agent(interface=device, **_agent_kwargs(script, file_name, report_dir))

    async def _teardown() -> None:
        if hasattr(device, "destroy"):
            try:
                await device.destroy()
            except Exception:  # noqa: BLE001
                pass

    return SetupResult(agent=agent, platform="interface", teardown=[_teardown])


async def setup_agent(
    script: MidsceneYamlScript,
    file_name: str,
    *,
    headed: bool = False,
    keep_window: bool = False,
    shared_context: Any = None,
    report_dir: str | None = None,
) -> SetupResult:
    """检测目标类型并构造对应平台的 agent。"""
    platform = detect_target_type(script)
    if platform == "web":
        return await _setup_web(
            script, file_name, headed, keep_window, shared_context, report_dir
        )
    if platform == "android":
        return await _setup_android(script, file_name, report_dir)
    if platform == "ios":
        return await _setup_ios(script, file_name, report_dir)
    return await _setup_interface(script, file_name, report_dir)


__all__ = ["SetupResult", "setup_agent"]
