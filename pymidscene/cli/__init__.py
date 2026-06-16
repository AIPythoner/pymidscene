"""
pymidscene 命令行 - 跑 Midscene YAML 自动化脚本(web / android / ios)。

入口:``pymidscene <script.yaml>`` 或 ``python -m pymidscene.cli ...``。
对齐 @midscene/cli 的命令面与 YAML 脚本/flow 执行契约。
"""

from .main import main

__all__ = ["main"]
