"""Smoke checks for installed report-template packaging."""

import asyncio
import re
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from pymidscene.core.agent.agent import Agent
from pymidscene.core.js_react_report_generator import JSReactReportGenerator
from pymidscene.core.types import ScreenshotItem, UIContext
from pymidscene.shared.types import Size
from pymidscene.web_integration.base import AbstractInterface


class _SmokeInterface(AbstractInterface):
    def __init__(self):
        self._screenshot_base64 = (
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwAD"
            "hgGAWjR9awAAAABJRU5ErkJggg=="
        )
        self._size: Size = {"width": 1280, "height": 720, "dpr": 1.0}

    async def get_ui_context(self) -> UIContext:
        return UIContext(
            screenshot=ScreenshotItem(self._screenshot_base64),
            size=self._size,
            _is_frozen=False,
        )

    async def get_size(self) -> Size:
        return self._size

    async def screenshot(self, full_page: bool = False) -> str:
        return self._screenshot_base64

    async def click(self, x: float, y: float) -> None:
        return None

    async def input_text(
        self,
        text: str,
        x: float | None = None,
        y: float | None = None,
    ) -> None:
        return None

    async def hover(self, x: float, y: float) -> None:
        return None

    async def scroll(self, direction: str, distance: int | None = None) -> None:
        return None

    async def key_press(self, key: str) -> None:
        return None

    async def wait_for_navigation(self, timeout: int | None = None) -> None:
        return None

    async def wait_for_network_idle(self, timeout: int | None = None) -> None:
        return None

    async def evaluate_javascript(self, script: str):
        return None


async def _generate_report_html() -> str:
    with TemporaryDirectory() as temp_dir:
        agent = Agent(
            interface=_SmokeInterface(),
            model_config={
                "MIDSCENE_MODEL_NAME": "qwen-vl-max",
                "MIDSCENE_MODEL_BASE_URL": "https://example.invalid/v1",
                "MIDSCENE_MODEL_API_KEY": "test-api-key",
                "MIDSCENE_MODEL_FAMILY": "qwen2.5-vl",
            },
            enable_recording=True,
            report_dir=temp_dir,
        )

        with patch.object(
            JSReactReportGenerator,
            "_js_template_cache",
            None,
        ), patch.object(
            JSReactReportGenerator,
            "JS_TEMPLATE_SOURCES",
            [],
        ), patch(
            "glob.glob",
            return_value=[],
        ), patch.object(
            agent,
            "_call_ai_with_config",
            return_value={"content": '{"bbox": [10, 20, 110, 120]}', "usage": None},
        ):
            await agent.ai_locate("report template smoke target")
            report_path = agent.finish()

        assert (
            report_path is not None
        ), "Smoke check expected Agent.finish() to create a report file."
        report_file = Path(report_path)
        assert (
            report_file.is_file()
        ), "Smoke check expected the generated report HTML file to exist."
        return report_file.read_text(encoding="utf-8")


def main() -> None:
    html = asyncio.run(_generate_report_html())
    matches = list(
        re.finditer(
            r'(<script[^>]*type="midscene_web_dump"[^>]*>)\s*(\{.*?\})\s*</script>',
            html,
            re.DOTALL,
        )
    )
    assert (
        len(matches) == 1
    ), "Generated report HTML should embed exactly one Midscene dump payload block."
    assert (
        matches[0].group(1) == '<script type="midscene_web_dump">'
    ), "Generated report HTML should use the corrected Midscene dump tag shape."
    assert "无法加载 JS 版本的 React 可视化模板" not in html, (
        "Generated report HTML should be rendered from packaged report_template resources, "
        "not the template-unavailable fallback page."
    )


def test_installed_artifact_can_generate_a_report_from_packaged_template_assets():
    main()


if __name__ == "__main__":
    main()
