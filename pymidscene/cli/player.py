"""
ScriptPlayer - 对齐 @midscene/core/src/yaml/player.ts。

负责跑 **一个** yaml 脚本:构造 agent -> 顺序执行每个 task 的 flow 步骤,把
每个 flow 步骤分派到对应的 ``ai_*`` / 平台方法,收集返回值并增量写到 output
JSON。错误处理:flow 步骤抛错则该 task 标记 error;除非 ``continueOnError``,
否则整个 player 停在 error。

Python 移植没有 JS 的 actionSpace/callActionInActionSpace 抽象,所以这里用
**显式 if/elif** 把每个 yaml flow key 映射到 Python 的 agent 方法;需要"按
坐标"的手势(LongPress/DragAndDrop/Swipe)用 ``ai_locate(prompt).center`` 把
定位描述桥接成坐标再调平台方法。
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from typing import Any

from ..core.run_manager import get_default_run_manager
from ..shared.logger import logger
from .agent_factory import setup_agent
from .yaml_script import MidsceneYamlScript, MidsceneYamlTask

# 旧 scrollType 别名 -> 规范值(对齐 JS)。
_SCROLL_TYPE_ALIASES = {
    "once": "singleAction",
    "untilBottom": "scrollToBottom",
    "untilTop": "scrollToTop",
    "untilRight": "scrollToRight",
    "untilLeft": "scrollToLeft",
}


@dataclass
class TaskStatus:
    name: str
    index: int
    total_steps: int
    status: str = "init"  # init | running | done | error
    current_step: int | None = None
    error: BaseException | None = None


def _locate_prompt(value: Any) -> str | None:
    """从 ``'text'`` 或 ``{prompt: 'text'}`` 这种 locate 简写里取出描述串。"""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        prompt = value.get("prompt") or value.get("locate")
        return str(prompt) if prompt is not None else None
    return None


class ScriptPlayer:
    """跑单个 yaml 脚本的执行器。"""

    def __init__(
        self,
        script: MidsceneYamlScript,
        file_path: str,
        timestamp: int,
        *,
        headed: bool = False,
        keep_window: bool = False,
        shared_context: Any = None,
        report_dir: str | None = None,
    ) -> None:
        self.script = script
        self.file_path = file_path
        self.file_name = os.path.splitext(os.path.basename(file_path))[0]
        self.headed = headed
        self.keep_window = keep_window
        self.shared_context = shared_context
        self.report_dir = report_dir

        self.status: str = "init"
        self.error_in_setup: BaseException | None = None
        self.report_file: str | None = None
        self.result: dict = {}
        self._unnamed_index = 0

        self.task_status_list: list[TaskStatus] = [
            TaskStatus(
                name=task.name or f"task-{i}",
                index=i,
                total_steps=len(task.flow),
            )
            for i, task in enumerate(self.script.tasks)
        ]

        self.output: str | None = self._resolve_output(timestamp)

    # ---- output / result ----------------------------------------------------

    def _resolve_output(self, timestamp: int) -> str | None:
        # `output` 是 MidsceneYamlScriptConfig 的字段, web/android/ios 块都
        # extends 它, 所以优先从目标块取(对齐 JS `this.target?.output`,
        # target = web||android||ios||config), 再回落顶层 config。
        out = self.script.target_block.get("output")
        if out:
            return os.path.abspath(out)
        try:
            output_dir = get_default_run_manager().output_dir
            return str(output_dir / f"{self.file_name}-{timestamp}.json")
        except Exception:  # noqa: BLE001
            return None

    def _set_result(self, name: str | None, value: Any) -> None:
        key: Any
        if name:
            if name in self.result:
                logger.warning(f"Duplicate result key '{name}', overwriting")
            key = name
        else:
            key = self._unnamed_index
            self._unnamed_index += 1
        self.result[key] = value
        self._flush_result()

    def _flush_result(self) -> None:
        if not self.output:
            return
        try:
            os.makedirs(os.path.dirname(self.output), exist_ok=True)
            with open(self.output, "w", encoding="utf-8") as fh:
                json.dump(self.result, fh, ensure_ascii=False, indent=2)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Failed to write output file {self.output}: {exc}")

    def has_failed_tasks(self) -> bool:
        return any(t.status == "error" for t in self.task_status_list)

    # ---- lifecycle ----------------------------------------------------------

    async def run(self) -> None:
        self.status = "running"
        try:
            setup = await setup_agent(
                self.script,
                self.file_name,
                headed=self.headed,
                keep_window=self.keep_window,
                shared_context=self.shared_context,
                report_dir=self.report_dir,
            )
        except Exception as exc:  # noqa: BLE001
            self.error_in_setup = exc
            self.status = "error"
            logger.error(f"[{self.file_name}] setup failed: {exc}")
            return

        agent = setup.agent
        platform = setup.platform
        error_flag = False
        try:
            for task_status in self.task_status_list:
                task = self.script.tasks[task_status.index]
                task_status.status = "running"
                try:
                    await self._play_task(task, task_status, agent, platform)
                    task_status.status = "done"
                except Exception as exc:  # noqa: BLE001
                    task_status.status = "error"
                    task_status.error = exc
                    logger.error(
                        f"[{self.file_name}] task '{task.name}' failed: {exc}"
                    )
                    if task.continue_on_error:
                        continue
                    error_flag = True
                    break
            self.status = "error" if error_flag else "done"
        finally:
            try:
                self.report_file = agent.finish()
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[{self.file_name}] finish() failed: {exc}")
            for fn in reversed(setup.teardown):
                try:
                    await fn()
                except Exception:  # noqa: BLE001
                    pass

    async def _play_task(
        self,
        task: MidsceneYamlTask,
        task_status: TaskStatus,
        agent: Any,
        platform: str,
    ) -> None:
        for step_index, flow_item in enumerate(task.flow):
            task_status.current_step = step_index
            if not isinstance(flow_item, dict):
                raise ValueError(
                    f"flow item must be a mapping, got {type(flow_item).__name__}"
                )
            await self._dispatch(flow_item, agent, platform)

    # ---- flow-item dispatch -------------------------------------------------

    async def _dispatch(self, item: dict, agent: Any, platform: str) -> None:
        # web/android/ios 包装器用 `.agent` 暴露底层 Agent;interface 目标
        # 直接就是 Agent(无 `.agent`),用 getattr 回落到自身。
        core = getattr(agent, "agent", agent)  # 底层 Agent,完整 ai_* 方法面
        name = item.get("name")

        # 1) aiAct / aiAction / ai —— 完整 plan-execute-replan,无返回值存储
        if "aiAct" in item or "aiAction" in item or "ai" in item:
            prompt = item.get("aiAct") or item.get("aiAction") or item.get("ai")
            await core.ai_act(str(prompt))
            return

        # 2) aiAssert —— 存 {pass, thought, message},失败抛错
        if "aiAssert" in item:
            res = await core.ai_assert(
                str(item["aiAssert"]),
                item.get("errorMessage") or "",
                keep_raw_response=True,
            )
            self._set_result(name, res)
            if isinstance(res, dict) and not res.get("pass", False):
                raise AssertionError(
                    res.get("message") or f"Assertion failed: {item['aiAssert']}"
                )
            return

        # 3) 数据提取族 —— 都存返回值
        if "aiQuery" in item:
            res = await core.ai_query(
                item["aiQuery"], use_cache=bool(item.get("cacheable", False))
            )
            data = res.get("data", res) if isinstance(res, dict) else res
            self._set_result(name, data)
            return
        if "aiNumber" in item:
            self._set_result(name, await core.ai_number(str(item["aiNumber"])))
            return
        if "aiString" in item:
            self._set_result(name, await core.ai_string(str(item["aiString"])))
            return
        if "aiBoolean" in item:
            self._set_result(name, await core.ai_boolean(str(item["aiBoolean"])))
            return
        if "aiAsk" in item:
            self._set_result(name, await core.ai_ask(str(item["aiAsk"])))
            return
        if "aiLocate" in item:
            el = await core.ai_locate(str(item["aiLocate"]))
            located = (
                {"rect": getattr(el, "rect", None), "center": getattr(el, "center", None)}
                if el is not None
                else None
            )
            self._set_result(name, located)
            return

        # 4) aiWaitFor —— yaml timeout 单位是毫秒,走 core 的 *_ms 路径
        if "aiWaitFor" in item:
            timeout = item.get("timeout")
            # 规范选项名是 checkIntervalMs(JS rest-spread 透传);也容忍
            # checkInterval 简写。
            interval = item.get("checkIntervalMs", item.get("checkInterval"))
            await core.ai_wait_for(
                str(item["aiWaitFor"]),
                timeout_ms=int(timeout) if timeout is not None else None,
                check_interval_ms=int(interval) if interval is not None else None,
            )
            return

        # 5) sleep —— 直接等待,毫秒
        if "sleep" in item:
            ms = int(item["sleep"])
            if ms <= 0:
                raise ValueError("sleep value must be > 0 ms")
            await asyncio.sleep(ms / 1000)
            return

        # 6) javascript —— 在 interface 上执行,存返回值
        if "javascript" in item:
            iface = agent.interface
            if not hasattr(iface, "evaluate_javascript"):
                raise ValueError(
                    f"'javascript' is not supported on the {platform} target"
                )
            self._set_result(
                name, await iface.evaluate_javascript(str(item["javascript"]))
            )
            return

        # 7) logScreenshot / recordToReport —— Python 报告暂无手动插入截图入口
        if "logScreenshot" in item or "recordToReport" in item:
            title = item.get("recordToReport") or item.get("logScreenshot") or "untitled"
            logger.warning(
                f"logScreenshot/recordToReport ('{title}') is not supported by "
                f"the Python report yet; skipping."
            )
            return

        # 8) aiInput —— 兼容新旧两种写法。以 `locate` 是否存在区分(对齐 JS:
        #    locate 在 -> 旧式 {aiInput: value, locate: prompt}(value 缺时回落
        #    到 value 字段);locate 不在 -> 新式 {aiInput: prompt, value}。
        if "aiInput" in item:
            if item.get("locate"):
                text = item.get("aiInput")
                if text in (None, ""):
                    text = item.get("value")
                prompt = _locate_prompt(item.get("locate"))
            else:
                prompt = _locate_prompt(item.get("aiInput"))
                text = item.get("value")
            if not prompt:
                raise ValueError("aiInput requires a locate prompt")
            await core.ai_input(
                str(prompt), str(text), mode=item.get("mode", "replace")
            )
            return

        # 9) aiKeyboardPress —— 兼容新旧两种写法 + 可选 locate(按键前先聚焦
        #    目标元素,对齐 JS KeyboardPress 的 locate 语义)。
        if "aiKeyboardPress" in item:
            key = item.get("keyName") or item["aiKeyboardPress"]
            locate = _locate_prompt(item.get("locate"))
            if not locate and item.get("keyName"):
                # 新式:{aiKeyboardPress: prompt, keyName: key}
                locate = _locate_prompt(item.get("aiKeyboardPress"))
            if locate:
                await core.ai_tap(locate)  # 聚焦元素后再按键
            await core.ai_keyboard_press(str(key))
            return

        # 10) aiScroll
        if "aiScroll" in item:
            scroll_type = item.get("scrollType", "singleAction")
            scroll_type = _SCROLL_TYPE_ALIASES.get(scroll_type, scroll_type)
            locate = item.get("locate") or _locate_prompt(item.get("aiScroll"))
            distance = item.get("distance")
            await core.ai_scroll(
                item.get("direction", "down"),
                int(distance) if distance is not None else None,
                scroll_type,
                locate,
            )
            return

        # 11) 通用动作(JS 里走 actionSpace,这里显式映射)
        await self._dispatch_generic(item, agent, platform, name)

    async def _dispatch_generic(
        self, item: dict, agent: Any, platform: str, name: str | None
    ) -> None:
        core = getattr(agent, "agent", agent)

        if "aiTap" in item:
            await core.ai_tap(self._require_prompt(item["aiTap"], "aiTap"))
            return
        if "aiRightClick" in item:
            await core.ai_right_click(
                self._require_prompt(item["aiRightClick"], "aiRightClick")
            )
            return
        if "aiDoubleClick" in item:
            await core.ai_double_click(
                self._require_prompt(item["aiDoubleClick"], "aiDoubleClick")
            )
            return
        if "aiHover" in item:
            await core.ai_hover(self._require_prompt(item["aiHover"], "aiHover"))
            return
        if "aiClearInput" in item:
            prompt = _locate_prompt(item["aiClearInput"])
            if not prompt:
                raise ValueError("aiClearInput requires a locate prompt")
            await core.ai_input(str(prompt), "", mode="clear")
            return
        if "aiDragAndDrop" in item:
            from_prompt = _locate_prompt(item.get("from"))
            to_prompt = _locate_prompt(item.get("to"))
            if not from_prompt or not to_prompt:
                raise ValueError("aiDragAndDrop requires 'from' and 'to' locates")
            fx, fy = await self._locate_center(core, from_prompt)
            tx, ty = await self._locate_center(core, to_prompt)
            await self._do_drag(agent, platform, fx, fy, tx, ty)
            return
        if "LongPress" in item or "longPress" in item:
            prompt = _locate_prompt(item.get("locate"))
            if not prompt:
                raise ValueError("LongPress requires a 'locate' prompt")
            x, y = await self._locate_center(core, prompt)
            await self._do_long_press(agent, platform, x, y, item.get("duration", 500))
            return
        if "Swipe" in item or "swipe" in item:
            await self._do_swipe(item, agent, platform, core)
            return
        if "launch" in item or "Launch" in item:
            uri = item.get("launch") or item.get("Launch")
            if not hasattr(agent, "launch"):
                raise ValueError(f"'launch' is not supported on the {platform} target")
            result = await agent.launch(str(uri))
            if result is not None:
                self._set_result(name, result)
            return
        if "runAdbShell" in item or "RunAdbShell" in item:
            cmd = item.get("runAdbShell") or item.get("RunAdbShell")
            if not hasattr(agent, "run_adb_shell"):
                raise ValueError("runAdbShell is only supported on the android target")
            self._set_result(name, await agent.run_adb_shell(str(cmd)))
            return
        if "runWdaRequest" in item:
            if not hasattr(agent, "run_wda_request"):
                raise ValueError("runWdaRequest is only supported on the ios target")
            params = item["runWdaRequest"] or {}
            if not isinstance(params, dict):
                raise ValueError(
                    "runWdaRequest expects a mapping with method/endpoint/data"
                )
            self._set_result(
                name,
                await agent.run_wda_request(
                    params.get("method", "GET"),
                    params.get("endpoint", ""),
                    params.get("data"),
                ),
            )
            return

        raise ValueError(
            f"unknown flowItem in yaml: {sorted(k for k in item if k != 'name')}"
        )

    # ---- generic helpers ----------------------------------------------------

    @staticmethod
    def _require_prompt(value: Any, key: str) -> str:
        prompt = _locate_prompt(value)
        if not prompt:
            raise ValueError(f"{key} requires a locate prompt")
        return prompt

    @staticmethod
    async def _locate_center(core: Any, prompt: str) -> tuple[float, float]:
        el = await core.ai_locate(prompt)
        if el is None or getattr(el, "center", None) is None:
            raise ValueError(f"Could not locate element: {prompt}")
        cx, cy = el.center
        return float(cx), float(cy)

    @staticmethod
    async def _do_long_press(
        agent: Any, platform: str, x: float, y: float, duration: Any
    ) -> None:
        dur = int(duration or 500)
        if platform == "web":
            await agent.interface.long_press(x, y, dur)
        else:
            await agent.long_press(x, y, dur)

    @staticmethod
    async def _do_drag(
        agent: Any, platform: str, fx: float, fy: float, tx: float, ty: float
    ) -> None:
        if platform == "web":
            await agent.interface.drag_and_drop(fx, fy, tx, ty)
        else:
            await agent.drag_and_drop((fx, fy), (tx, ty))

    async def _do_swipe(
        self, item: dict, agent: Any, platform: str, core: Any
    ) -> None:
        start = _locate_prompt(item.get("start"))
        end = _locate_prompt(item.get("end"))
        if start and end:
            fx, fy = await self._locate_center(core, start)
            tx, ty = await self._locate_center(core, end)
            await self._do_drag(agent, platform, fx, fy, tx, ty)
            return
        direction = item.get("direction")
        if direction:
            logger.warning(
                "Swipe by direction+distance is mapped to ai_scroll on the "
                "Python CLI; for precise control use start/end locates."
            )
            distance = item.get("distance")
            await core.ai_scroll(
                direction,
                int(distance) if distance is not None else None,
                "singleAction",
                None,
            )
            return
        raise ValueError("Swipe requires either start+end locates or a direction")


__all__ = ["ScriptPlayer", "TaskStatus"]
