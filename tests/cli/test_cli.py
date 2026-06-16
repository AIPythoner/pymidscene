"""
pymidscene CLI 测试:yaml 加载 + 环境插值、参数解析(点号命名空间)、config
工厂三层优先级、flow 步骤分派(用 FakeAgent)、BatchRunner 分类/汇总/退出码。

不触碰真实浏览器/模型:通过 monkeypatch ``pymidscene.cli.player.setup_agent``
注入一个假 agent。
"""

from __future__ import annotations

import json
import os
from types import SimpleNamespace

import pytest

from pymidscene.cli import args as cli_args
from pymidscene.cli import config as cli_config
from pymidscene.cli import player as player_mod
from pymidscene.cli.agent_factory import SetupResult
from pymidscene.cli.batch_runner import BatchRunner
from pymidscene.cli.config import BatchRunnerConfig
from pymidscene.cli.player import ScriptPlayer
from pymidscene.cli.yaml_script import (
    detect_target_type,
    interpolate_env_vars,
    parse_yaml_script,
)

# --- env interpolation -------------------------------------------------------

class TestInterpolateEnvVars:
    def test_replaces_defined_var(self, monkeypatch):
        monkeypatch.setenv("MY_URL", "https://example.com")
        assert interpolate_env_vars("url: ${MY_URL}") == "url: https://example.com"

    def test_skips_comment_lines(self, monkeypatch):
        text = "# ${UNDEFINED_VAR} in a comment\nname: ok"
        assert interpolate_env_vars(text) == text

    def test_raises_on_undefined(self, monkeypatch):
        monkeypatch.delenv("NOPE_VAR", raising=False)
        with pytest.raises(ValueError, match="not defined"):
            interpolate_env_vars("x: ${NOPE_VAR}")


# --- yaml script schema ------------------------------------------------------

class TestParseYamlScript:
    def test_target_normalized_to_web(self):
        script = parse_yaml_script(
            "target:\n  url: http://a.com\ntasks:\n  - name: t\n    flow: []"
        )
        assert script.web == {"url": "http://a.com"}
        assert detect_target_type(script) == "web"

    def test_missing_tasks_raises(self):
        with pytest.raises(ValueError, match="tasks"):
            parse_yaml_script("web:\n  url: http://a.com")

    def test_numeric_device_id_quoted(self):
        script = parse_yaml_script(
            "android:\n  deviceId: 0123456\ntasks:\n  - name: t\n    flow: []"
        )
        # 数字 deviceId 被加引号 -> 解析成字符串而非数字
        assert script.android["deviceId"] == "0123456"

    def test_multiple_targets_raises(self):
        script = parse_yaml_script(
            "web:\n  url: http://a.com\nandroid:\n  deviceId: x\n"
            "tasks:\n  - name: t\n    flow: []"
        )
        with pytest.raises(ValueError, match="Only one target"):
            detect_target_type(script)

    def test_no_target_raises(self):
        script = parse_yaml_script("tasks:\n  - name: t\n    flow: []")
        with pytest.raises(ValueError, match="No valid interface"):
            detect_target_type(script)


# --- argument parsing --------------------------------------------------------

class TestArgs:
    def test_dotted_web_namespace_both_formats(self):
        opt = cli_args.parse_args(
            ["s.yaml", "--web.viewportWidth", "1920", "--headed"]
        )
        assert opt.path == "s.yaml"
        assert opt.headed is True
        # 同时存 kebab 与 camel,且数值被转成 int
        assert opt.web["viewportWidth"] == 1920
        assert opt.web["viewport-width"] == 1920

    def test_inline_equals_and_android_namespace(self):
        opt = cli_args.parse_args(["--android.deviceId=emulator-5554", "x.yaml"])
        assert opt.android["deviceId"] == "emulator-5554"
        assert opt.path == "x.yaml"

    def test_files_nargs_and_flags(self):
        opt = cli_args.parse_args(
            ["--files", "a.yaml", "b.yaml", "--concurrent", "3",
             "--continue-on-error"]
        )
        assert opt.files == ["a.yaml", "b.yaml"]
        assert opt.concurrent == 3
        assert opt.continue_on_error is True
        # 未给的 flag 是 None(未设置),便于三层优先级判断
        assert opt.headed is None

    def test_url_legacy_captured(self):
        opt = cli_args.parse_args(["--url", "http://a.com"])
        assert opt.url == "http://a.com"


# --- config factory ----------------------------------------------------------

class TestConfig:
    def test_deep_merge_override_wins(self):
        merged = cli_config._deep_merge(
            {"a": 1, "nested": {"x": 1, "y": 2}},
            {"nested": {"y": 3, "z": 4}},
        )
        assert merged == {"a": 1, "nested": {"x": 1, "y": 3, "z": 4}}

    def test_match_yaml_files_in_dir(self, tmp_path):
        (tmp_path / "b.yaml").write_text("tasks: []")
        (tmp_path / "a.yml").write_text("tasks: []")
        (tmp_path / "ignore.txt").write_text("nope")
        matched = cli_config.match_yaml_files(str(tmp_path))
        names = [os.path.basename(p) for p in matched]
        assert names == ["a.yml", "b.yaml"]  # 排序、过滤非 yaml

    def test_create_files_config_cli_precedence(self, tmp_path):
        f = tmp_path / "s.yaml"
        f.write_text("web:\n  url: http://a.com\ntasks: []")
        opt = cli_args.parse_args([str(f), "--concurrent", "5", "--keep-window"])
        cfg = cli_config.create_files_config([str(f)], opt, timestamp=123)
        assert cfg.concurrent == 5
        assert cfg.keep_window is True
        assert cfg.headed is True  # keep_window 强制 headed
        assert cfg.summary == "summary-123.json"
        assert len(cfg.files) == 1

    def test_create_config_requires_files_array(self, tmp_path):
        cfg_yaml = tmp_path / "suite.yaml"
        cfg_yaml.write_text("concurrent: 2\n")  # 没有 files:
        opt = cli_args.parse_args(["--config", str(cfg_yaml)])
        with pytest.raises(ValueError, match="files"):
            cli_config.create_config(str(cfg_yaml), opt, timestamp=1)

    def test_create_config_merges_and_cli_overrides(self, tmp_path):
        script = tmp_path / "s.yaml"
        script.write_text("web:\n  url: http://a.com\ntasks: []")
        cfg_yaml = tmp_path / "suite.yaml"
        cfg_yaml.write_text(
            f"files:\n  - {script.name}\nconcurrent: 2\ncontinueOnError: true\n"
        )
        # CLI 不传 concurrent -> 用 config 的 2;CLI 传 --concurrent 9 -> 覆盖
        opt = cli_args.parse_args(["--config", str(cfg_yaml)])
        cfg = cli_config.create_config(str(cfg_yaml), opt, timestamp=1)
        assert cfg.concurrent == 2
        assert cfg.continue_on_error is True

        opt2 = cli_args.parse_args(["--config", str(cfg_yaml), "--concurrent", "9"])
        cfg2 = cli_config.create_config(str(cfg_yaml), opt2, timestamp=1)
        assert cfg2.concurrent == 9


# --- fake agent for flow dispatch -------------------------------------------

class FakeCore:
    """记录每次 ai_* 调用的假核心 Agent。"""

    def __init__(self):
        self.calls: list = []

    async def ai_act(self, p):
        self.calls.append(("ai_act", p))
        return True

    async def ai_tap(self, p):
        self.calls.append(("ai_tap", p))
        return True

    async def ai_hover(self, p):
        self.calls.append(("ai_hover", p))
        return True

    async def ai_right_click(self, p):
        self.calls.append(("ai_right_click", p))
        return True

    async def ai_double_click(self, p):
        self.calls.append(("ai_double_click", p))
        return True

    async def ai_input(self, p, t, mode="replace"):
        self.calls.append(("ai_input", p, t, mode))
        return True

    async def ai_keyboard_press(self, k):
        self.calls.append(("ai_keyboard_press", k))
        return True

    async def ai_scroll(self, direction, distance, scroll_type, locate):
        self.calls.append(("ai_scroll", direction, distance, scroll_type, locate))
        return True

    async def ai_assert(self, assertion, message="", keep_raw_response=False):
        self.calls.append(("ai_assert", assertion))
        passed = "FAIL" not in assertion
        return {
            "pass": passed,
            "thought": "reasoning",
            "message": "" if passed else f"Assertion failed: {assertion}",
        }

    async def ai_query(self, demand, use_cache=False):
        self.calls.append(("ai_query", demand, use_cache))
        return {"data": {"title": "hello"}}

    async def ai_number(self, q):
        return 42.0

    async def ai_string(self, q):
        return "str-answer"

    async def ai_boolean(self, q):
        return True

    async def ai_ask(self, q):
        return "free answer"

    async def ai_locate(self, p):
        self.calls.append(("ai_locate", p))
        return SimpleNamespace(center=(11.0, 22.0), rect={"left": 0, "top": 0})

    async def ai_wait_for(self, assertion, timeout_ms=None, check_interval_ms=None):
        self.calls.append(("ai_wait_for", assertion, timeout_ms, check_interval_ms))
        return True


class FakeAgent:
    def __init__(self, platform="web"):
        self.agent = FakeCore()
        self.finished = False

        async def _eval_js(script):
            self.agent.calls.append(("evaluate_javascript", script))
            return {"ok": True}

        async def _long_press(x, y, d):
            self.agent.calls.append(("iface_long_press", x, y, d))

        async def _drag(fx, fy, tx, ty):
            self.agent.calls.append(("iface_drag", fx, fy, tx, ty))

        self.interface = SimpleNamespace(
            evaluate_javascript=_eval_js,
            long_press=_long_press,
            drag_and_drop=_drag,
        )

    def finish(self):
        self.finished = True
        return "/tmp/report.html"

    async def launch(self, uri):
        self.agent.calls.append(("launch", uri))

    async def run_adb_shell(self, cmd):
        self.agent.calls.append(("run_adb_shell", cmd))
        return "shell-output"


def _patch_setup(monkeypatch, agent, platform="web"):
    async def _fake_setup(script, file_name, **kwargs):
        return SetupResult(agent=agent, platform=platform, teardown=[])

    monkeypatch.setattr(player_mod, "setup_agent", _fake_setup)


@pytest.fixture
def run_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("MIDSCENE_RUN_DIR", str(tmp_path / "midscene_run"))
    from pymidscene.core import run_manager as rm

    rm._default_manager = None
    yield tmp_path
    rm._default_manager = None


def _script(flow: list) -> player_mod.MidsceneYamlScript:
    from pymidscene.cli.yaml_script import MidsceneYamlScript, MidsceneYamlTask

    return MidsceneYamlScript(
        raw={},
        web={"url": "http://a.com"},
        tasks=[MidsceneYamlTask(name="t", flow=flow)],
    )


# --- flow dispatch -----------------------------------------------------------

class TestFlowDispatch:
    @pytest.mark.asyncio
    async def test_basic_verbs_dispatched(self, monkeypatch, run_dir):
        agent = FakeAgent()
        _patch_setup(monkeypatch, agent)
        script = _script([
            {"aiTap": "login button"},
            {"aiInput": "search box", "value": 123, "mode": "append"},
            {"sleep": 1},
            {"aiKeyboardPress": "Enter"},
        ])
        player = ScriptPlayer(script, "myscript.yaml", 999)
        await player.run()
        assert player.status == "done"
        assert ("ai_tap", "login button") in agent.agent.calls
        # value 转字符串,mode 透传
        assert ("ai_input", "search box", "123", "append") in agent.agent.calls
        assert ("ai_keyboard_press", "Enter") in agent.agent.calls
        assert agent.finished is True

    @pytest.mark.asyncio
    async def test_query_result_stored_and_flushed(self, monkeypatch, run_dir):
        agent = FakeAgent()
        _patch_setup(monkeypatch, agent)
        script = _script([{"aiQuery": {"title": "string"}, "name": "page"}])
        player = ScriptPlayer(script, "q.yaml", 1)
        await player.run()
        assert player.result["page"] == {"title": "hello"}
        # 增量写入 output JSON
        assert player.output and os.path.exists(player.output)
        with open(player.output, encoding="utf-8") as fh:
            assert json.load(fh)["page"] == {"title": "hello"}

    @pytest.mark.asyncio
    async def test_aiwaitfor_passes_ms(self, monkeypatch, run_dir):
        agent = FakeAgent()
        _patch_setup(monkeypatch, agent)
        script = _script([{"aiWaitFor": "loaded", "timeout": 5000}])
        player = ScriptPlayer(script, "w.yaml", 1)
        await player.run()
        assert ("ai_wait_for", "loaded", 5000, None) in agent.agent.calls

    @pytest.mark.asyncio
    async def test_assert_failure_marks_task_error(self, monkeypatch, run_dir):
        agent = FakeAgent()
        _patch_setup(monkeypatch, agent)
        script = _script([{"aiAssert": "this will FAIL"}])
        player = ScriptPlayer(script, "a.yaml", 1)
        await player.run()
        assert player.status == "error"
        assert player.task_status_list[0].status == "error"

    @pytest.mark.asyncio
    async def test_continue_on_error_keeps_going(self, monkeypatch, run_dir):
        from pymidscene.cli.yaml_script import MidsceneYamlScript, MidsceneYamlTask

        agent = FakeAgent()
        _patch_setup(monkeypatch, agent)
        script = MidsceneYamlScript(
            raw={},
            web={"url": "http://a.com"},
            tasks=[
                MidsceneYamlTask(
                    name="bad", flow=[{"aiAssert": "FAIL here"}],
                    continue_on_error=True,
                ),
                MidsceneYamlTask(name="good", flow=[{"aiTap": "ok"}]),
            ],
        )
        player = ScriptPlayer(script, "c.yaml", 1)
        await player.run()
        # 整体没停在 error(因为 continueOnError),但有失败任务
        assert player.status == "done"
        assert player.has_failed_tasks() is True
        assert ("ai_tap", "ok") in agent.agent.calls

    @pytest.mark.asyncio
    async def test_unknown_flow_item_raises_task_error(self, monkeypatch, run_dir):
        agent = FakeAgent()
        _patch_setup(monkeypatch, agent)
        script = _script([{"frobnicate": "???"}])
        player = ScriptPlayer(script, "u.yaml", 1)
        await player.run()
        assert player.status == "error"
        assert isinstance(player.task_status_list[0].error, ValueError)

    @pytest.mark.asyncio
    async def test_longpress_bridges_locate_to_coords(self, monkeypatch, run_dir):
        agent = FakeAgent(platform="web")
        _patch_setup(monkeypatch, agent, platform="web")
        script = _script([{"LongPress": True, "locate": "an item", "duration": 600}])
        player = ScriptPlayer(script, "lp.yaml", 1)
        await player.run()
        assert player.status == "done"
        # ai_locate(prompt).center -> interface.long_press(x, y, dur)
        assert ("ai_locate", "an item") in agent.agent.calls
        assert ("iface_long_press", 11.0, 22.0, 600) in agent.agent.calls

    @pytest.mark.asyncio
    async def test_javascript_on_interface(self, monkeypatch, run_dir):
        agent = FakeAgent()
        _patch_setup(monkeypatch, agent)
        script = _script([{"javascript": "return 1", "name": "js"}])
        player = ScriptPlayer(script, "j.yaml", 1)
        await player.run()
        assert player.result["js"] == {"ok": True}


# --- batch runner ------------------------------------------------------------

class TestBatchRunner:
    def _write(self, tmp_path, name, flow_yaml):
        f = tmp_path / name
        f.write_text(
            "web:\n  url: http://a.com\ntasks:\n  - name: t\n    flow:\n"
            + flow_yaml
        )
        return str(f)

    @pytest.mark.asyncio
    async def test_summary_and_exit_code_all_pass(
        self, monkeypatch, run_dir, tmp_path
    ):
        agent = FakeAgent()
        _patch_setup(monkeypatch, agent)
        f1 = self._write(tmp_path, "a.yaml", "      - aiTap: x\n")
        cfg = BatchRunnerConfig(files=[f1], summary="sum.json")
        runner = BatchRunner(cfg, timestamp=1)
        results = await runner.run()
        assert results[0].result_type == "success"
        assert runner.print_execution_summary() is True

    @pytest.mark.asyncio
    async def test_stop_on_error_marks_not_executed(
        self, monkeypatch, run_dir, tmp_path
    ):
        # 每个文件一个新 FakeAgent;第一个文件的断言失败 -> 停止 -> 第二个 notExecuted
        def _fake_setup_factory():
            async def _fake_setup(script, file_name, **kwargs):
                return SetupResult(agent=FakeAgent(), platform="web", teardown=[])
            return _fake_setup

        monkeypatch.setattr(player_mod, "setup_agent", _fake_setup_factory())
        f1 = self._write(tmp_path, "a.yaml", '      - aiAssert: "will FAIL"\n')
        f2 = self._write(tmp_path, "b.yaml", "      - aiTap: x\n")
        cfg = BatchRunnerConfig(
            files=[f1, f2], summary="sum.json", concurrent=1,
            continue_on_error=False,
        )
        runner = BatchRunner(cfg, timestamp=1)
        results = await runner.run()
        assert results[0].result_type == "failed"
        assert results[1].result_type == "notExecuted"
        assert runner.print_execution_summary() is False
        # summary 索引文件已生成
        summary_file = runner._summary_path()
        assert os.path.exists(summary_file)
        with open(summary_file, encoding="utf-8") as fh:
            data = json.load(fh)
        assert data["summary"]["failed"] == 1
        assert data["summary"]["notExecuted"] == 1

    @pytest.mark.asyncio
    async def test_continue_on_error_runs_all(
        self, monkeypatch, run_dir, tmp_path
    ):
        def _fake_setup(script, file_name, **kwargs):
            async def _inner():
                return SetupResult(agent=FakeAgent(), platform="web", teardown=[])
            return _inner()

        monkeypatch.setattr(player_mod, "setup_agent", _fake_setup)
        f1 = self._write(tmp_path, "a.yaml", '      - aiAssert: "will FAIL"\n')
        f2 = self._write(tmp_path, "b.yaml", "      - aiTap: x\n")
        cfg = BatchRunnerConfig(
            files=[f1, f2], summary="sum.json", concurrent=2,
            continue_on_error=True,
        )
        runner = BatchRunner(cfg, timestamp=1)
        results = await runner.run()
        # 都执行了:一个 failed,一个 success(没有 notExecuted)
        types = sorted(r.result_type for r in results)
        assert types == ["failed", "success"]
