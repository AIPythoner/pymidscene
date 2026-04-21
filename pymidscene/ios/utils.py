"""iOS 工具 - 对应 packages/ios/src/utils.ts 的精简版."""

from __future__ import annotations

import asyncio
import os
import platform
from typing import Any, Optional

from ..shared.env.constants import (
    DEFAULT_WDA_HOST,
    DEFAULT_WDA_PORT,
    MIDSCENE_WDA_BASE_URL,
    MIDSCENE_WDA_HOST,
    MIDSCENE_WDA_PORT,
)
from ..shared.logger import logger


async def check_ios_environment(
    wda_host: Optional[str] = None,
    wda_port: Optional[int] = None,
    base_url: Optional[str] = None,
    timeout: float = 3.0,
) -> dict[str, Any]:
    """
    探测 WDA 是否可达. 不强求 macOS — 只要 WDA 的 HTTP 端点有响应就算可用.

    对齐 JS `checkIOSEnvironment` 但不依赖 xcodebuild (Python 版不托管 WDA).

    Returns:
        ``{"available": bool, "error": str | None, "status": dict | None}``
    """
    host = wda_host or os.environ.get(MIDSCENE_WDA_HOST) or DEFAULT_WDA_HOST
    port = int(
        wda_port or os.environ.get(MIDSCENE_WDA_PORT) or DEFAULT_WDA_PORT
    )
    url = base_url or os.environ.get(MIDSCENE_WDA_BASE_URL) or f"http://{host}:{port}"

    import httpx  # type: ignore

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(f"{url}/status")
        if resp.status_code >= 400:
            return {
                "available": False,
                "error": f"WDA /status returned HTTP {resp.status_code}",
                "status": None,
            }
        try:
            body = resp.json()
        except Exception:
            body = None
        return {"available": True, "error": None, "status": body}
    except Exception as exc:
        return {
            "available": False,
            "error": (
                f"Unable to reach WDA at {url} ({exc}). "
                "Start WebDriverAgent first (Xcode / tidevice xctest / simulator)."
            ),
            "status": None,
        }


async def agent_from_webdriver_agent(
    device_opt: Optional["IOSDeviceOpt"] = None,  # type: ignore[name-defined]  # noqa: F821
    **agent_kwargs,
) -> "IOSAgent":  # type: ignore[name-defined]  # noqa: F821
    """
    一键创建已连接的 IOSAgent. 对齐 JS `agentFromWebDriverAgent`.

    Args:
        device_opt: IOSDeviceOpt.
        **agent_kwargs: 透传给 IOSAgent.
    """
    from .agent import IOSAgent
    from .device import IOSDevice, IOSDeviceOpt

    opt = device_opt or IOSDeviceOpt()
    device = IOSDevice(options=opt)
    await device.connect()
    return IOSAgent(device=device, **agent_kwargs)


def is_macos() -> bool:
    return platform.system() == "Darwin"


__all__ = [
    "check_ios_environment",
    "agent_from_webdriver_agent",
    "is_macos",
]
