"""
命令行输出 - 对齐 @midscene/cli 的 printer / batch-runner 输出。

JS 版有一套 TTY 实时窗口渲染(tty-renderer.ts),那纯属视觉效果;这里用
非 TTY 的顺序打印作为忠实的功能等价物(JS 自己在非 TTY 下也是这么打的)。
"""

from __future__ import annotations

from typing import Any

# 状态字形(对齐 JS indicatorForStatus,去掉颜色以保证跨平台)。
_GLYPH = {
    "success": "✔",
    "done": "✔",
    "failed": "✘",
    "error": "✘",
    "partialFailed": "⚠",
    "notExecuted": "⏸",
    "init": "◌",
}


def welcome_banner(version: str) -> str:
    return f"\nWelcome to pymidscene CLI v{version}\n"


def print_execution_plan(config: Any, files: list[str]) -> None:
    print("   Scripts:")
    for file in files:
        print(f"     - {file}")
    print("📋 Execution plan")
    print(f"   Concurrency: {config.concurrent}")
    print(f"   Keep window: {config.keep_window}")
    print(f"   Headed: {config.headed}")
    print(f"   Continue on error: {config.continue_on_error}")
    print(f"   Share browser context: {config.share_browser_context}")
    print(f"   Summary output: {config.summary}")


def print_file_result(result: Any) -> None:
    """打印单个文件的结果行 + 缩进的 report/output/error 子行。"""
    glyph = _GLYPH.get(result.result_type, "•")
    print(f"{glyph} {result.file}")
    if result.report:
        print(f"  report: {result.report}")
    if result.output:
        print(f"  output: {result.output}")
    if result.error and not result.success:
        print(f"  error: {result.error}")


def print_execution_summary(summary: dict, summary_path: str, results: list) -> bool:
    """打印 📊 汇总块并返回总体成功布尔(供退出码使用)。"""
    print("\n📊 Execution Summary:")
    print(f"   Total files: {summary['total']}")
    print(f"   Successful: {summary['successful']}")
    print(f"   Failed: {summary['failed']}")
    print(f"   Partial failed: {summary['partialFailed']}")
    print(f"   Not executed: {summary['notExecuted']}")
    print(f"   Duration: {summary['totalDuration'] / 1000:.2f}s")
    print(f"   Summary: {summary_path}")

    def _files_of(rtype: str) -> list[str]:
        return [r.file for r in results if r.result_type == rtype]

    successful = _files_of("success")
    failed = _files_of("failed")
    partial = _files_of("partialFailed")
    not_executed = _files_of("notExecuted")

    if successful:
        print("\n✅ Successful files:")
        for f in successful:
            print(f"   {f}")
    if failed:
        print("\n❌ Failed files:")
        for f in failed:
            print(f"   {f}")
    if partial:
        print("\n⚠️  Partial failed files (some tasks failed with continueOnError):")
        for f in partial:
            print(f"   {f}")
    if not_executed:
        print("\n⏸️ Not executed files:")
        for f in not_executed:
            print(f"   {f}")

    success = (
        summary["failed"] == 0
        and summary["partialFailed"] == 0
        and summary["notExecuted"] == 0
    )
    if success:
        print("\n🎉 All files executed successfully!")
    else:
        print("\n⚠️ Some files failed or were not executed.")
    return success


__all__ = [
    "welcome_banner",
    "print_execution_plan",
    "print_file_result",
    "print_execution_summary",
]
