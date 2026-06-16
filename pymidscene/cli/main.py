"""
pymidscene CLI 入口 - 对齐 @midscene/cli/src/index.ts 的顶层控制流。

流程:解析参数 -> 打印欢迎横幅 -> 校验(config/path/files 至少其一)-> 构造
BatchRunnerConfig -> 加载 ``<cwd>/.env`` -> 跑 BatchRunner -> 打印汇总 -> 按
是否全部成功返回退出码(0/1);``keep_window`` 时挂起不退出(对齐 JS)。
"""

from __future__ import annotations

import asyncio
import os
import sys
import time

from .. import __version__
from ..shared.logger import logger
from .args import parse_args
from .batch_runner import BatchRunner
from .config import BatchRunnerConfig, create_config, create_files_config, match_yaml_files
from .printer import welcome_banner


def _load_dotenv(config: BatchRunnerConfig) -> None:
    """加载 ``<cwd>/.env``(若存在),override/debug 取自已合并的配置。"""
    dotenv_path = os.path.join(os.getcwd(), ".env")
    if not os.path.exists(dotenv_path):
        return
    try:
        from dotenv import load_dotenv

        print(f"   Env file: {dotenv_path}")
        load_dotenv(
            dotenv_path,
            override=config.dotenv_override,
            verbose=config.dotenv_debug,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Failed to load .env: {exc}")


async def _amain(argv: list[str]) -> int:
    options = parse_args(argv)
    print(welcome_banner(__version__))

    if options.url:
        print(
            "the cli mode is no longer supported, please use a yaml file instead "
            "(see https://midscenejs.com/automate-with-scripts-in-yaml.html).",
            file=sys.stderr,
        )
        return 1

    if not options.config and not options.path and not (options.files):
        print(
            "No script path, files, or config provided.", file=sys.stderr
        )
        return 1

    timestamp = int(time.time() * 1000)
    try:
        if options.config:
            print(f"   Config file: {options.config}")
            config = create_config(options.config, options, timestamp)
        elif options.files:
            print("   Executing YAML files from --files argument...")
            config = create_files_config(options.files, options, timestamp)
        else:
            assert options.path is not None
            matched = match_yaml_files(options.path)
            if not matched:
                print(f"No yaml files found in {options.path}", file=sys.stderr)
                return 1
            print("   Executing YAML files...")
            config = create_files_config([options.path], options, timestamp)
    except Exception as exc:  # noqa: BLE001
        print(f"Could not create a valid configuration: {exc}", file=sys.stderr)
        return 1

    if not config.files:
        print("No yaml files found.", file=sys.stderr)
        return 1

    _load_dotenv(config)

    runner = BatchRunner(config, timestamp)
    await runner.run()
    success = runner.print_execution_summary()

    if config.keep_window:
        # 对齐 JS:不退出,每 5s 提示一次,直到 Ctrl+C。
        while True:
            print("browser is still running, use ctrl+c to stop it")
            await asyncio.sleep(5)

    return 0 if success else 1


def main(argv: list[str] | None = None) -> None:
    """同步入口(console_scripts 调用)。"""
    if argv is None:
        argv = sys.argv[1:]
    try:
        code = asyncio.run(_amain(argv))
    except KeyboardInterrupt:
        code = 130
    sys.exit(code)


__all__ = ["main"]
