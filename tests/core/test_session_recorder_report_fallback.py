"""Focused fallback tests for SessionRecorder HTML report generation."""

import logging
from pathlib import Path
from unittest.mock import patch

from pymidscene.core.dump import SessionRecorder


def _build_session_recorder(tmp_path: Path) -> SessionRecorder:
    recorder = SessionRecorder(
        base_dir=str(tmp_path),
        auto_save=False,
        use_js_react_report=True,
    )
    recorder.start_step("click", "Click the checkout button")
    recorder.complete_step()
    return recorder


def test_generate_report_falls_back_to_python_native_html_when_js_generation_fails(
    tmp_path: Path,
    caplog,
):
    recorder = _build_session_recorder(tmp_path)

    with patch.object(
        SessionRecorder,
        "_generate_js_react_report",
        side_effect=RuntimeError("official template generation exploded"),
    ):
        with caplog.at_level(logging.WARNING, logger="pymidscene"):
            html = recorder.generate_report()

    assert "Click the checkout button" in html
    assert '<div class="timeline">' in html
    assert "无法加载 JS 版本的 React 可视化模板" not in html
    assert "Official-style report generation failed" in caplog.text
    assert "official template generation exploded" in caplog.text


def test_save_report_falls_back_to_python_native_html_when_js_save_fails(
    tmp_path: Path,
    caplog,
):
    recorder = _build_session_recorder(tmp_path)

    with patch.object(
        SessionRecorder,
        "_save_js_react_report",
        side_effect=RuntimeError("official template save exploded"),
    ):
        with caplog.at_level(logging.WARNING, logger="pymidscene"):
            report_path = recorder.save_report("fallback.html")

    html = Path(report_path).read_text(encoding="utf-8")

    assert Path(report_path).name == "fallback.html"
    assert "Click the checkout button" in html
    assert '<div class="timeline">' in html
    assert "无法加载 JS 版本的 React 可视化模板" not in html
    assert "Official-style report save failed" in caplog.text
    assert "official template save exploded" in caplog.text


def test_save_report_raises_only_when_python_native_fallback_also_fails(
    tmp_path: Path,
    caplog,
):
    recorder = _build_session_recorder(tmp_path)

    with patch.object(
        SessionRecorder,
        "_save_js_react_report",
        side_effect=RuntimeError("official template save exploded"),
    ), patch.object(
        recorder.report_generator,
        "save",
        side_effect=RuntimeError("python native save exploded"),
    ):
        with caplog.at_level(logging.WARNING, logger="pymidscene"):
            try:
                recorder.save_report("fallback.html")
            except RuntimeError as exc:
                assert str(exc) == "python native save exploded"
            else:
                raise AssertionError("Expected the Python-native fallback failure to be raised.")

    assert "Official-style report save failed" in caplog.text
    assert "official template save exploded" in caplog.text
