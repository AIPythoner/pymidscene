"""
MidsceneYamlScript 模式 + 加载 + 环境变量插值

对齐 @midscene/core/src/yaml(packages/core/src/yaml/utils.ts、yaml.ts)。

一个 YAML 脚本顶层是 **一个** 平台配置块(``web`` / ``android`` / ``ios`` /
``interface``,其中 ``target`` 是 ``web`` 的废弃别名)加可选的 ``config`` /
``agent`` 块,再加一个必填的 ``tasks`` 数组。每个 task = ``{name, flow[],
continueOnError?}``。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

import yaml

# ${VAR} 插值(注释行不替换);对齐 JS interpolateEnvVars。
_ENV_VAR_RE = re.compile(r"\$\{([^}]+)\}")
# 数字 deviceId 自动加引号(YAML 会把 0123 之类当数字);对齐 JS 预处理。
_DEVICE_ID_RE = re.compile(r"(deviceId:\s*)(\d+)\b")


def interpolate_env_vars(content: str) -> str:
    """把 ``${VAR}`` 替换成环境变量值;注释行(# 开头)跳过;未定义则报错。

    对齐 JS ``interpolateEnvVars``:纯文本替换,发生在 yaml.load 之前,所以
    config/脚本里只能引用 **已在环境中** 的变量。
    """

    def _replace_line(line: str) -> str:
        if line.lstrip().startswith("#"):
            return line

        def repl(match: re.Match[str]) -> str:
            name = match.group(1).strip()
            value = os.environ.get(name)
            if value is None:
                raise ValueError(f'Environment variable "{name}" is not defined')
            return value

        return _ENV_VAR_RE.sub(repl, line)

    return "\n".join(_replace_line(line) for line in content.split("\n"))


@dataclass
class MidsceneYamlTask:
    """单个任务:一组按顺序执行的 flow 步骤。"""

    name: str
    flow: list[dict]
    continue_on_error: bool = False


@dataclass
class MidsceneYamlScript:
    """解析后的 YAML 脚本文档。"""

    raw: dict
    web: dict | None = None
    android: dict | None = None
    ios: dict | None = None
    interface: dict | None = None
    config: dict = field(default_factory=dict)
    agent: dict = field(default_factory=dict)
    tasks: list[MidsceneYamlTask] = field(default_factory=list)

    @property
    def target_block(self) -> dict:
        """供 ``config.output`` 等读取的"目标块"(web/android/ios/config 优先级)。"""
        return self.web or self.android or self.ios or self.config or {}


def parse_yaml_script(
    content: str, file_path: str | None = None
) -> MidsceneYamlScript:
    """把 YAML 文本解析成 :class:`MidsceneYamlScript`。

    步骤对齐 JS ``parseYamlScript``:
    1. 含 ``android`` 时给数字 deviceId 加引号(避免被当数字);
    2. ``${VAR}`` 环境变量插值;
    3. yaml.safe_load;
    4. 断言 ``tasks`` 是数组;
    5. 把废弃的 ``target`` 规整成 ``web``。
    """
    if "android" in content:
        content = _DEVICE_ID_RE.sub(r'\1"\2"', content)

    interpolated = interpolate_env_vars(content)
    data = yaml.safe_load(interpolated)

    if not isinstance(data, dict):
        raise ValueError(
            f"Invalid yaml script (expected a mapping at top level): {file_path}"
        )

    tasks_raw = data.get("tasks")
    if not isinstance(tasks_raw, list):
        raise ValueError(
            f'yaml script must contain a "tasks" array: {file_path}'
        )

    # 废弃的 target 规整为 web(文件内 web 优先叠加在 target 之上)。
    web = data.get("web")
    target = data.get("target")
    if target is not None:
        if isinstance(target, dict):
            web = {**target, **(web or {})}
        elif web is None:
            web = target

    tasks: list[MidsceneYamlTask] = []
    for raw_task in tasks_raw:
        if not isinstance(raw_task, dict):
            raise ValueError(f"Each task must be a mapping: {file_path}")
        flow = raw_task.get("flow") or []
        if not isinstance(flow, list):
            raise ValueError(
                f"task '{raw_task.get('name')}' flow must be a list: {file_path}"
            )
        tasks.append(
            MidsceneYamlTask(
                name=str(raw_task.get("name", "")),
                flow=list(flow),
                continue_on_error=bool(raw_task.get("continueOnError", False)),
            )
        )

    return MidsceneYamlScript(
        raw=data,
        web=web,
        android=data.get("android"),
        ios=data.get("ios"),
        interface=data.get("interface"),
        config=data.get("config") or {},
        agent=data.get("agent") or {},
        tasks=tasks,
    )


def load_yaml_script(file_path: str) -> MidsceneYamlScript:
    """从磁盘读取并解析一个 YAML 脚本文件。"""
    with open(file_path, encoding="utf-8") as fh:
        content = fh.read()
    return parse_yaml_script(content, file_path)


def detect_target_type(script: MidsceneYamlScript) -> str:
    """返回 ``'web'|'android'|'ios'|'interface'``;若有 0 或 ≥2 个则报错。

    对齐 create-yaml-player.ts 的目标检测:只允许恰好一个平台块。
    """
    present = [
        name
        for name, value in (
            ("web", script.web),
            ("android", script.android),
            ("ios", script.ios),
            ("interface", script.interface),
        )
        if value is not None
    ]
    if len(present) > 1:
        raise ValueError(
            "Only one target type can be specified, but found multiple: "
            + ", ".join(present)
        )
    if not present:
        raise ValueError(
            "No valid interface configuration found "
            "(expected one of: web / android / ios / interface)"
        )
    return present[0]


__all__ = [
    "interpolate_env_vars",
    "MidsceneYamlTask",
    "MidsceneYamlScript",
    "parse_yaml_script",
    "load_yaml_script",
    "detect_target_type",
]
