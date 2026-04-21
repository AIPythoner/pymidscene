"""
Android 工具函数 - 对应 packages/android/src/utils.ts

主要提供连接设备的辅助函数.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Optional

from ..shared.env.constants import (
    MIDSCENE_ADB_PATH,
    MIDSCENE_ADB_REMOTE_HOST,
    MIDSCENE_ADB_REMOTE_PORT,
)
from ..shared.logger import logger

try:
    import adbutils  # type: ignore[import-not-found]
    _HAS_ADBUTILS = True
except ImportError:  # pragma: no cover
    adbutils = None  # type: ignore[assignment]
    _HAS_ADBUTILS = False


@dataclass
class ConnectedDevice:
    """对应 appium-adb 的 `Device` (简化)."""

    udid: str  # 设备 serial
    state: str  # 'device' / 'offline' / 'unauthorized' ...


async def get_connected_devices() -> list[ConnectedDevice]:
    """
    列出当前通过 adb 连上的设备. 对齐 JS `getConnectedDevices`.

    Raises:
        RuntimeError: adb 不可用或 adbutils 未安装.
    """
    if not _HAS_ADBUTILS:
        raise RuntimeError(
            "adbutils is not installed. Install the android extra: "
            "`pip install pymidscene[android]`."
        )
    try:
        devices = await asyncio.to_thread(_list_devices_sync)
    except Exception as exc:
        raise RuntimeError(
            f"Unable to get connected Android device list, please check "
            f"https://midscenejs.com/integrate-with-android.html#faq: {exc}"
        ) from exc
    logger.debug(f"Found {len(devices)} connected Android device(s)")
    return devices


def _list_devices_sync() -> list[ConnectedDevice]:
    """在工作线程里同步拉取设备列表."""
    assert adbutils is not None
    adb_host = os.environ.get(MIDSCENE_ADB_REMOTE_HOST)
    adb_port = os.environ.get(MIDSCENE_ADB_REMOTE_PORT)
    adb_path = os.environ.get(MIDSCENE_ADB_PATH)
    if adb_path:
        os.environ.setdefault("ADB_PATH", adb_path)
    if adb_host:
        client = adbutils.AdbClient(
            host=adb_host, port=int(adb_port) if adb_port else 5037
        )
    else:
        client = adbutils.adb
    return [
        ConnectedDevice(udid=info.serial, state=info.state)
        for info in client.list()
    ]


async def agent_from_adb_device(
    device_id: Optional[str] = None,
    device_opt: Optional["AndroidDeviceOpt"] = None,  # type: ignore[name-defined]  # noqa: F821
    **agent_kwargs,
) -> "AndroidAgent":  # type: ignore[name-defined]  # noqa: F821
    """
    一键创建连接好的 AndroidAgent. 对齐 JS `agentFromAdbDevice`.

    Args:
        device_id: 设备 serial. 为空则选第一台连上的设备.
        device_opt: 设备选项.
        **agent_kwargs: 透传给 AndroidAgent (model_config / cache_id 等).

    Returns:
        已经 connect() 好的 AndroidAgent.
    """
    # 懒加载以避免在包导入阶段 import adbutils
    from .agent import AndroidAgent
    from .device import AndroidDevice, AndroidDeviceOpt

    if not device_id:
        devices = await get_connected_devices()
        online = [d for d in devices if d.state == "device"]
        if not online:
            raise RuntimeError(
                "No Android devices found. Please connect an Android device "
                "and ensure ADB is properly configured. Run `adb devices` to verify."
            )
        device_id = online[0].udid
        logger.info(
            f"device_id not specified, using the first device: {device_id}"
        )

    opt = device_opt or AndroidDeviceOpt()
    device = AndroidDevice(device_id=device_id, options=opt)
    await device.connect()
    return AndroidAgent(device=device, **agent_kwargs)


__all__ = [
    "ConnectedDevice",
    "get_connected_devices",
    "agent_from_adb_device",
]
