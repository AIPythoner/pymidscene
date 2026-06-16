"""
命令行参数解析 - 对齐 @midscene/cli 的 yargs 参数面。

只有一个(默认)命令,无子命令。三种互斥的脚本选取方式:
1. 位置参数 ``path``:单个 yaml 文件 / 目录 / glob;
2. ``--files a.yaml b.yaml``:显式列表/glob;
3. ``--config config.yaml``:索引配置(其 ``files:`` 数组列出脚本)。

``--web.* / --android.* / --ios.*`` 用点号命名空间表示目标环境覆盖
(yargs dot-notation)。stdlib argparse 不支持点号,这里在交给 argparse
之前先把这些 token 抽出来组装成嵌套 dict,并对每个 key 同时存 kebab 和
camel 两种写法(对齐 JS ensureBothFormats)。
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass, field
from typing import Any

_DOTTED_RE = re.compile(r"^--(web|android|ios)\.(.+)$")


def _coerce(value: str) -> Any:
    """把命令行字符串轻量转成数字(镜像 yargs dot-notation)。

    yargs 只把"干净"的数字转成 number, 其余(含 ``true``/``false`` 以及带
    前导零的串如 ``007``)保持字符串。特意不把 ``true``/``false`` 转成 bool ——
    yargs 保留字符串(在 JS 里 ``'false'`` 还是 truthy), 转 bool 会改变下游
    web/android/ios env 的真值判断。
    """
    if re.fullmatch(r"-?[1-9]\d*|0", value):
        return int(value)
    if re.fullmatch(r"-?\d+\.\d+", value):
        return float(value)
    return value


def _kebab_to_camel(key: str) -> str:
    parts = key.split("-")
    return parts[0] + "".join(p[:1].upper() + p[1:] for p in parts[1:])


def _camel_to_kebab(key: str) -> str:
    return re.sub(r"([A-Z])", lambda m: "-" + m.group(1).lower(), key)


def _store_both_formats(target: dict, key: str, value: Any) -> None:
    """同时存 kebab 和 camel 两种 key,下游无论哪种命名都能取到。"""
    if "-" in key or key.islower():
        kebab, camel = _camel_to_kebab(key), _kebab_to_camel(key)
    else:
        camel, kebab = key, _camel_to_kebab(key)
    target[kebab] = value
    target[camel] = value


def _extract_dotted(argv: list[str]) -> tuple[list[str], dict, dict, dict]:
    """抽出 ``--web.x val`` / ``--web.x=val`` 形式,返回剩余 argv 和三个 env dict。"""
    web: dict = {}
    android: dict = {}
    ios: dict = {}
    namespaces = {"web": web, "android": android, "ios": ios}

    remaining: list[str] = []
    i = 0
    while i < len(argv):
        token = argv[i]
        key_part: str | None = None
        ns_name: str | None = None
        inline_value: str | None = None

        if "=" in token:
            head, _, tail = token.partition("=")
            match = _DOTTED_RE.match(head)
            if match:
                ns_name, key_part, inline_value = match.group(1), match.group(2), tail
        else:
            match = _DOTTED_RE.match(token)
            if match:
                ns_name, key_part = match.group(1), match.group(2)

        if ns_name is None or key_part is None:
            remaining.append(token)
            i += 1
            continue

        if inline_value is not None:
            value: Any = _coerce(inline_value)
        elif i + 1 < len(argv) and not argv[i + 1].startswith("--"):
            value = _coerce(argv[i + 1])
            i += 1
        else:
            # 末尾裸 flag 视为布尔 true(对齐 yargs)。
            value = True

        _store_both_formats(namespaces[ns_name], key_part, value)
        i += 1

    return remaining, web, android, ios


@dataclass
class CliOptions:
    """规整后的命令行选项。"""

    path: str | None = None
    files: list[str] | None = None
    config: str | None = None
    summary: str | None = None
    concurrent: int | None = None
    continue_on_error: bool | None = None
    headed: bool | None = None
    keep_window: bool | None = None
    share_browser_context: bool | None = None
    dotenv_override: bool | None = None
    dotenv_debug: bool | None = None
    url: str | None = None  # 废弃,出现即报错
    web: dict = field(default_factory=dict)
    android: dict = field(default_factory=dict)
    ios: dict = field(default_factory=dict)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pymidscene",
        description="Run Midscene YAML automation scripts (web / android / ios).",
        epilog=(
            "Examples:\n"
            "  pymidscene ./script.yaml\n"
            "  pymidscene ./scripts/            # run every *.yaml under the dir\n"
            "  pymidscene --files a.yaml b.yaml --concurrent 2\n"
            "  pymidscene --config ./suite.yaml --continue-on-error\n"
            "  pymidscene ./web.yaml --headed --web.viewportWidth 1920\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("path", nargs="?", default=None,
                        help="A yaml file, a directory, or a glob pattern.")
    parser.add_argument("--files", nargs="*", default=None,
                        help="Explicit list of yaml files/globs to run.")
    parser.add_argument("--config", default=None,
                        help="Path to an index/config yaml with a files: array.")
    parser.add_argument("--summary", default=None,
                        help="Filename for the summary output JSON.")
    parser.add_argument("--concurrent", type=int, default=None,
                        help="Number of concurrent file executions (default 1).")
    parser.add_argument("--continue-on-error", dest="continue_on_error",
                        action="store_true", default=None,
                        help="Run all files even if some fail.")
    parser.add_argument("--headed", action="store_true", default=None,
                        help="Run the browser in headed (visible) mode.")
    parser.add_argument("--keep-window", dest="keep_window",
                        action="store_true", default=None,
                        help="Keep the browser window open after scripts finish.")
    parser.add_argument("--share-browser-context", dest="share_browser_context",
                        action="store_true", default=None,
                        help="Share one browser instance across all web yaml files.")
    parser.add_argument("--dotenv-override", dest="dotenv_override",
                        action="store_true", default=None,
                        help="Let .env override existing environment variables.")
    parser.add_argument("--dotenv-debug", dest="dotenv_debug",
                        action="store_true", default=None,
                        help="Enable dotenv debug logging.")
    # 废弃:旧的 --url 脚本模式;注册仅为捕获后报错(对齐 JS)。
    parser.add_argument("--url", default=None, help=argparse.SUPPRESS)
    return parser


def parse_args(argv: list[str]) -> CliOptions:
    """解析命令行,返回 :class:`CliOptions`。"""
    remaining, web, android, ios = _extract_dotted(list(argv))
    parser = build_parser()
    ns = parser.parse_args(remaining)
    return CliOptions(
        path=ns.path,
        files=ns.files,
        config=ns.config,
        summary=ns.summary,
        concurrent=ns.concurrent,
        continue_on_error=ns.continue_on_error,
        headed=ns.headed,
        keep_window=ns.keep_window,
        share_browser_context=ns.share_browser_context,
        dotenv_override=ns.dotenv_override,
        dotenv_debug=ns.dotenv_debug,
        url=ns.url,
        web=web,
        android=android,
        ios=ios,
    )


__all__ = ["CliOptions", "build_parser", "parse_args"]
