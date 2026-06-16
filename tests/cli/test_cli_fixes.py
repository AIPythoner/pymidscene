"""
回归测试:锁定 CLI 对抗审查(cli-review)确认并修复的问题。

覆盖:interface 目标的 `.agent` 解析、output 从目标块读取、aiInput 新旧式以
`locate` 区分、aiKeyboardPress 的 locate 先聚焦、yargs 风格的值转换、--files
相对 config 目录解析、runWdaRequest 非 dict 守卫。
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from pymidscene.cli import args as cli_args
from pymidscene.cli import config as cli_config
from pymidscene.cli import player as player_mod
from pymidscene.cli.agent_factory import SetupResult
from pymidscene.cli.player import ScriptPlayer
from pymidscene.cli.yaml_script import MidsceneYamlScript, MidsceneYamlTask


class FakeCore:
    def __init__(self):
        self.calls: list = []

    async def ai_tap(self, p):
        self.calls.append(("ai_tap", p))
        return True

    async def ai_input(self, p, t, mode="replace"):
        self.calls.append(("ai_input", p, t, mode))
        return True

    async def ai_keyboard_press(self, k):
        self.calls.append(("ai_keyboard_press", k))
        return True

    async def ai_query(self, demand, use_cache=False):
        return {"data": {"ok": True}}


class FakeWrapper:
    """像 web/android/ios 包装器:用 .agent 暴露 core。"""

    def __init__(self, platform="web"):
        self.agent = FakeCore()

        async def _rwr(method, endpoint, data=None):
            self.agent.calls.append(("run_wda_request", method, endpoint, data))
            return "ok"

        self.run_wda_request = _rwr
        self.interface = SimpleNamespace()

    def finish(self):
        return "/tmp/report.html"


class FakeBareAgent(FakeCore):
    """像 interface 目标返回的裸 core Agent:ai_* 直接在自身,没有 .agent。"""

    def __init__(self):
        super().__init__()

        async def _eval(script):
            self.calls.append(("evaluate_javascript", script))
            return {"ok": True}

        self.interface = SimpleNamespace(evaluate_javascript=_eval)

    def finish(self):
        return "/tmp/report.html"


def _patch(monkeypatch, agent, platform="web"):
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


def _web_script(flow):
    return MidsceneYamlScript(
        raw={}, web={"url": "http://a.com"},
        tasks=[MidsceneYamlTask(name="t", flow=flow)],
    )


# --- interface target: bare Agent has no .agent (was a hard crash) -----------

@pytest.mark.asyncio
async def test_interface_target_dispatches_on_bare_agent(monkeypatch, run_dir):
    bare = FakeBareAgent()
    _patch(monkeypatch, bare, platform="interface")
    script = MidsceneYamlScript(
        raw={}, interface={"module": "x"},
        tasks=[MidsceneYamlTask(name="t", flow=[
            {"aiTap": "a button"},
            {"javascript": "return 1", "name": "js"},
        ])],
    )
    player = ScriptPlayer(script, "iface.yaml", 1)
    await player.run()
    assert player.status == "done"
    assert ("ai_tap", "a button") in bare.calls
    assert player.result["js"] == {"ok": True}


# --- output resolved from the web/android/ios block --------------------------

def test_output_read_from_web_block(run_dir):
    script = MidsceneYamlScript(
        raw={}, web={"url": "http://a.com", "output": "./out.json"}, tasks=[]
    )
    player = ScriptPlayer(script, "o.yaml", 1)
    assert player.output == os.path.abspath("./out.json")


def test_output_falls_back_to_default_when_unset(run_dir):
    script = MidsceneYamlScript(raw={}, web={"url": "http://a.com"}, tasks=[])
    player = ScriptPlayer(script, "o.yaml", 7)
    assert player.output is not None
    assert player.output.endswith("o-7.json")


# --- aiInput: branch on `locate` presence (mirror JS) ------------------------

@pytest.mark.asyncio
async def test_aiinput_old_format_locate_present(monkeypatch, run_dir):
    agent = FakeWrapper()
    _patch(monkeypatch, agent)
    player = ScriptPlayer(
        _web_script([{"aiInput": "hello", "locate": "the box"}]), "a.yaml", 1
    )
    await player.run()
    assert ("ai_input", "the box", "hello", "replace") in agent.agent.calls


@pytest.mark.asyncio
async def test_aiinput_new_format_value(monkeypatch, run_dir):
    agent = FakeWrapper()
    _patch(monkeypatch, agent)
    player = ScriptPlayer(
        _web_script([{"aiInput": "the box", "value": "hello"}]), "a.yaml", 1
    )
    await player.run()
    assert ("ai_input", "the box", "hello", "replace") in agent.agent.calls


@pytest.mark.asyncio
async def test_aiinput_conflicting_keys_prefer_locate(monkeypatch, run_dir):
    # 三键同时给(歧义输入):locate 在 -> 旧式(text=aiInput, prompt=locate)
    agent = FakeWrapper()
    _patch(monkeypatch, agent)
    player = ScriptPlayer(
        _web_script([{"aiInput": "box-text", "value": "v", "locate": "L"}]),
        "a.yaml", 1,
    )
    await player.run()
    assert ("ai_input", "L", "box-text", "replace") in agent.agent.calls


# --- aiKeyboardPress: focus located element before pressing ------------------

@pytest.mark.asyncio
async def test_keyboardpress_with_locate_focuses_first(monkeypatch, run_dir):
    agent = FakeWrapper()
    _patch(monkeypatch, agent)
    player = ScriptPlayer(
        _web_script([{"aiKeyboardPress": "search box", "keyName": "Enter"}]),
        "k.yaml", 1,
    )
    await player.run()
    calls = agent.agent.calls
    assert ("ai_tap", "search box") in calls
    assert ("ai_keyboard_press", "Enter") in calls
    assert calls.index(("ai_tap", "search box")) < calls.index(
        ("ai_keyboard_press", "Enter")
    )


@pytest.mark.asyncio
async def test_keyboardpress_plain_key_no_focus(monkeypatch, run_dir):
    agent = FakeWrapper()
    _patch(monkeypatch, agent)
    player = ScriptPlayer(
        _web_script([{"aiKeyboardPress": "Enter"}]), "k.yaml", 1
    )
    await player.run()
    calls = agent.agent.calls
    assert ("ai_keyboard_press", "Enter") in calls
    assert not any(c[0] == "ai_tap" for c in calls)


# --- runWdaRequest non-dict guard -------------------------------------------

@pytest.mark.asyncio
async def test_runwdarequest_non_dict_raises(monkeypatch, run_dir):
    agent = FakeWrapper()
    _patch(monkeypatch, agent, platform="ios")
    player = ScriptPlayer(_web_script([{"runWdaRequest": "/status"}]), "w.yaml", 1)
    await player.run()
    assert player.status == "error"
    assert isinstance(player.task_status_list[0].error, ValueError)


# --- yargs-style value coercion ---------------------------------------------

class TestCoercion:
    def test_true_false_kept_as_string(self):
        opt = cli_args.parse_args(
            ["s.yaml", "--web.acceptInsecureCerts", "false"]
        )
        assert opt.web["acceptInsecureCerts"] == "false"

    def test_leading_zero_kept_as_string(self):
        opt = cli_args.parse_args(["s.yaml", "--android.deviceId", "007"])
        assert opt.android["deviceId"] == "007"

    def test_clean_int_and_float_coerced(self):
        opt = cli_args.parse_args(
            ["s.yaml", "--web.viewportWidth", "1920", "--web.scale", "1.5",
             "--web.zero", "0"]
        )
        assert opt.web["viewportWidth"] == 1920
        assert opt.web["scale"] == 1.5
        assert opt.web["zero"] == 0


# --- --files resolved against the config file's dir --------------------------

def test_config_files_resolved_against_config_dir(tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "extra.yaml").write_text("web:\n  url: http://a.com\ntasks: []")
    cfg_yaml = sub / "suite.yaml"
    cfg_yaml.write_text("files:\n  - other.yaml\n")  # config's own list (unused)
    # --files extra.yaml must resolve relative to sub/ (the config dir), not cwd
    opt = cli_args.parse_args(["--config", str(cfg_yaml), "--files", "extra.yaml"])
    cfg = cli_config.create_config(str(cfg_yaml), opt, timestamp=1)
    assert len(cfg.files) == 1
    assert os.path.basename(cfg.files[0]) == "extra.yaml"
