"""
BatchRunner - 对齐 @midscene/cli/src/batch-runner.ts。

编排多个 yaml 文件:加载并把 ``global_config`` 叠加到每个脚本的目标块上 ->
按 ``concurrent`` 并发执行(asyncio 信号量替代 p-limit)-> ``continueOnError``
为 False 时首个失败后停止调度,余下记为 notExecuted -> 汇总分类、写 summary
索引 JSON、计算退出码。可选 ``share_browser_context`` 时全局共用一个浏览器。
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ..core.run_manager import get_default_run_manager
from ..shared.logger import logger
from . import printer
from .config import BatchRunnerConfig, _deep_merge
from .player import ScriptPlayer
from .yaml_script import MidsceneYamlScript, load_yaml_script


@dataclass
class FileResult:
    file: str
    success: bool
    executed: bool
    result_type: str  # success | failed | partialFailed | notExecuted
    output: str | None = None
    report: str | None = None
    error: str | None = None
    duration: float = 0.0  # ms


def _apply_global_config(
    script: MidsceneYamlScript, global_config: dict
) -> None:
    """把 CLI/配置文件的 web/android/ios 覆盖叠加到脚本自身的目标块上。

    只在脚本已声明该目标、或脚本完全没有目标块时叠加,避免给一个纯
    android 脚本平白塞进一个 web 块而触发"multiple targets"。
    """
    has_target = any(
        getattr(script, k) is not None
        for k in ("web", "android", "ios", "interface")
    )
    for key in ("web", "android", "ios"):
        override = global_config.get(key)
        if not override:
            continue
        current = getattr(script, key)
        if current is not None:
            setattr(script, key, _deep_merge(current, override))
        elif not has_target:
            setattr(script, key, dict(override))


class BatchRunner:
    def __init__(self, config: BatchRunnerConfig, timestamp: int) -> None:
        self.config = config
        self.timestamp = timestamp
        self.results: list[FileResult] = []

    async def run(self) -> list[FileResult]:
        files = self.config.files
        printer.print_execution_plan(self.config, files)

        # 加载脚本 + 叠加 global_config。
        scripts: list[MidsceneYamlScript | None] = []
        for file in files:
            try:
                script = load_yaml_script(file)
                _apply_global_config(script, self.config.global_config)
                scripts.append(script)
            except Exception as exc:  # noqa: BLE001
                logger.error(f"Failed to load {file}: {exc}")
                scripts.append(None)

        needs_browser = any(s is not None and s.web for s in scripts)
        # 共享一个 context(不只是 browser)才能跨文件共享 cookie/会话 ——
        # Playwright 的 BrowserContext 才是隔离边界, 对齐 JS browser.newPage()
        # 同 browser 共享 cookie 的语义。
        shared_context, shared_browser, shared_pw = None, None, None
        if self.config.share_browser_context and needs_browser:
            shared_context, shared_browser, shared_pw = (
                await self._launch_shared_context()
            )

        try:
            results_by_idx = await self._execute(files, scripts, shared_context)
        finally:
            if not self.config.keep_window:
                for closer in (
                    getattr(shared_context, "close", None),
                    getattr(shared_browser, "close", None),
                    getattr(shared_pw, "stop", None),
                ):
                    if closer is None:
                        continue
                    try:
                        await closer()
                    except Exception:  # noqa: BLE001
                        pass

        self.results = [results_by_idx[i] for i in range(len(files))]
        self._generate_output_index()
        return self.results

    async def _launch_shared_context(self) -> tuple[Any, Any, Any]:
        from playwright.async_api import async_playwright

        pw = await async_playwright().start()
        browser = await pw.chromium.launch(headless=not self.config.headed)
        if self.config.headed:
            context = await browser.new_context(no_viewport=True)
        else:
            context = await browser.new_context()
        return context, browser, pw

    async def _execute(
        self,
        files: list[str],
        scripts: list[MidsceneYamlScript | None],
        shared_context: Any,
    ) -> dict[int, FileResult]:
        sem = asyncio.Semaphore(max(1, self.config.concurrent))
        stop = {"flag": False}
        results: dict[int, FileResult] = {}

        async def run_one(idx: int) -> None:
            file = files[idx]
            script = scripts[idx]
            async with sem:
                if script is None:
                    results[idx] = FileResult(
                        file=file,
                        success=False,
                        executed=False,
                        result_type="failed",
                        error="Failed to load script",
                    )
                    if not self.config.continue_on_error:
                        stop["flag"] = True
                    return
                if not self.config.continue_on_error and stop["flag"]:
                    results[idx] = self._not_executed(file)
                    return

                player = ScriptPlayer(
                    script,
                    file,
                    self.timestamp,
                    headed=self.config.headed,
                    keep_window=self.config.keep_window,
                    shared_context=shared_context,
                )
                start = time.perf_counter()
                await player.run()
                duration = (time.perf_counter() - start) * 1000
                results[idx] = self._classify(player, file, duration)

                if not self.config.continue_on_error and player.status == "error":
                    stop["flag"] = True

        await asyncio.gather(
            *(run_one(i) for i in range(len(files))), return_exceptions=True
        )

        # 任何既没执行、也没被标 notExecuted 的补成 notExecuted。
        for idx in range(len(files)):
            if idx not in results:
                results[idx] = self._not_executed(files[idx])
        return results

    @staticmethod
    def _not_executed(file: str) -> FileResult:
        return FileResult(
            file=file,
            success=False,
            executed=False,
            result_type="notExecuted",
            error="Not executed (previous task failed)",
            duration=0.0,
        )

    @staticmethod
    def _classify(player: ScriptPlayer, file: str, duration: float) -> FileResult:
        has_player_error = player.status == "error"
        has_failed_tasks = player.has_failed_tasks()

        if has_player_error:
            result_type = "failed"
            success = False
        elif has_failed_tasks:
            result_type = "partialFailed"
            success = False
        else:
            result_type = "success"
            success = True

        error: str | None = None
        if player.error_in_setup is not None:
            error = str(player.error_in_setup)
        elif has_player_error:
            failed = next(
                (t for t in player.task_status_list if t.error is not None), None
            )
            error = str(failed.error) if failed else "Execution failed"
        elif has_failed_tasks:
            error = "Some tasks failed"

        output = (
            player.output
            if player.output and os.path.exists(player.output) and player.result
            else None
        )
        return FileResult(
            file=file,
            success=success,
            executed=True,
            result_type=result_type,
            output=output,
            report=player.report_file,
            error=error,
            duration=duration,
        )

    def get_execution_summary(self) -> dict:
        counts = {
            "total": len(self.results),
            "successful": sum(1 for r in self.results if r.result_type == "success"),
            "failed": sum(1 for r in self.results if r.result_type == "failed"),
            "partialFailed": sum(
                1 for r in self.results if r.result_type == "partialFailed"
            ),
            "notExecuted": sum(
                1 for r in self.results if r.result_type == "notExecuted"
            ),
            "totalDuration": sum(r.duration for r in self.results),
        }
        return counts

    def _summary_path(self) -> str:
        output_dir = get_default_run_manager().output_dir
        return str(output_dir / self.config.summary)

    def _generate_output_index(self) -> None:
        summary_path = self._summary_path()
        output_dir = os.path.dirname(summary_path)
        summary = self.get_execution_summary()

        def _rel(path: str | None) -> str | None:
            if not path:
                return None
            try:
                return os.path.relpath(path, output_dir)
            except ValueError:
                return path

        def _rel_output(path: str | None) -> str | None:
            # output 字段加 './' 前缀(对齐 JS generateOutputIndex);script/
            # report 保持裸相对路径。
            rel = _rel(path)
            if rel and not rel.startswith("."):
                return "./" + rel
            return rel

        index_data = {
            "summary": {
                **summary,
                "generatedAt": datetime.now().astimezone().isoformat(),
            },
            "results": [
                {
                    "script": _rel(r.file),
                    "success": r.success,
                    "resultType": r.result_type,
                    "output": _rel_output(r.output),
                    "report": _rel(r.report),
                    "error": r.error,
                    "duration": r.duration,
                }
                for r in self.results
            ],
        }
        try:
            os.makedirs(output_dir, exist_ok=True)
            with open(summary_path, "w", encoding="utf-8") as fh:
                json.dump(index_data, fh, ensure_ascii=False, indent=2)
            logger.info("Execution finished.")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Failed to generate output index: {exc}")

    def print_execution_summary(self) -> bool:
        return printer.print_execution_summary(
            self.get_execution_summary(), self._summary_path(), self.results
        )


__all__ = ["BatchRunner", "FileResult"]
