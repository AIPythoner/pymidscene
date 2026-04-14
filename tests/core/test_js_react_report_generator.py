"""Contract tests for JSReactReportGenerator against the vendored report template."""

import json
import re
from importlib import resources
from pathlib import Path

from pymidscene.core.js_react_report_generator import JSReactReportGenerator

REPORT_TEMPLATE_PACKAGE = "pymidscene.resources.report_template"
PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwAD"
    "hgGAWjR9awAAAABJRU5ErkJggg=="
)


def _build_contract_report_html() -> str:
    return _build_contract_report_generator().generate_html()


def _build_contract_report_generator() -> JSReactReportGenerator:
    generator = JSReactReportGenerator()
    generator.start_session(
        group_name="Contract Compatibility Session",
        description="Verifies the vendored report template contract.",
        model_name="qwen-vl-max",
    )
    generator.add_task(
        task_type="Planning",
        sub_type="Locate",
        prompt="Locate the cart icon",
        screenshot_before=PNG_BASE64,
        screenshot_after=PNG_BASE64,
        element_rect={"left": 100, "top": 10, "width": 20, "height": 30},
        element_center=[110, 25],
        element_text="Cart icon",
        duration_ms=250,
        ai_prompt_tokens=11,
        ai_completion_tokens=7,
        screenshot_width=1280,
        screenshot_height=720,
    )
    generator.add_task(
        task_type="Insight",
        sub_type="Assert",
        prompt="The cart total remains visible",
        thought="The cart total matches the expectation.",
        output={
            "pass": True,
            "details": {
                "expected": "$39.98",
                "actual": "$39.98",
            },
        },
        duration_ms=75,
        ai_tokens=9,
    )
    return generator


def _extract_midscene_dump(html: str) -> dict:
    matches = list(
        re.finditer(
            r'<script[^>]*type="midscene_web_dump"[^>]*>\s*(.*?)\s*</script>',
            html,
            re.DOTALL,
        )
    )
    assert matches, "Generated HTML should embed a midscene_web_dump payload."
    return json.loads(matches[-1].group(1))


def _vendored_template_html() -> str:
    template_root = resources.files(REPORT_TEMPLATE_PACKAGE)
    return (template_root / "report.html").read_text(encoding="utf-8")


def _vendored_asset_refs() -> list[str]:
    refs = {
        ref
        for ref in re.findall(r'["\'](static/[^"\']+)["\']', _vendored_template_html())
        if not ref.endswith(".LICENSE.txt")
    }
    return sorted(refs)


def test_generator_dump_matches_vendored_template_compatibility_checklist():
    dump = _extract_midscene_dump(_build_contract_report_html())

    assert dump["groupName"] == "Contract Compatibility Session"
    assert dump["groupDescription"] == "Verifies the vendored report template contract."
    assert dump["modelBriefs"] == ["qwen-vl-max"]
    assert len(dump["executions"]) == 2
    assert all(execution["tasks"] for execution in dump["executions"])

    locate_task = dump["executions"][0]["tasks"][0]
    assert locate_task["param"]["prompt"] == "Locate the cart icon"
    assert locate_task["output"]["element"]["description"] == "Cart icon"
    assert locate_task["recorder"]
    assert all(item["type"] == "screenshot" for item in locate_task["recorder"])
    assert all(
        item["screenshot"]["base64"].startswith("data:image/png;base64,")
        for item in locate_task["recorder"]
    )
    assert locate_task["uiContext"]["screenshot"]["base64"].startswith("data:image/png;base64,")
    assert locate_task["uiContext"]["size"] == {
        "width": 1280,
        "height": 720,
        "dpr": 1,
    }
    assert locate_task["timing"]["cost"] == 250
    assert locate_task["usage"] == {
        "prompt_tokens": 11,
        "completion_tokens": 7,
        "total_tokens": 18,
    }

    assert_task = dump["executions"][1]["tasks"][0]
    assert assert_task["thought"] == "The cart total matches the expectation."
    assert assert_task["output"]["details"] == {
        "expected": "$39.98",
        "actual": "$39.98",
    }
    assert assert_task["timing"]["cost"] == 75
    assert assert_task["usage"]["total_tokens"] == 9


def test_generator_exposes_upstream_locate_result_details_for_matched_elements():
    dump = _extract_midscene_dump(_build_contract_report_html())

    matched_element = dump["executions"][0]["tasks"][0]["matchedElement"][0]

    assert matched_element["description"] == "Cart icon"
    assert matched_element["center"] == [110, 25]
    assert matched_element["rect"] == {
        "left": 100,
        "top": 10,
        "width": 20,
        "height": 30,
    }


def test_generated_html_keeps_vendored_asset_references_intact():
    asset_refs = _vendored_asset_refs()
    template_root = resources.files(REPORT_TEMPLATE_PACKAGE)
    html = _build_contract_report_html()

    assert asset_refs, "Vendored template should reference packaged static assets."

    for asset_ref in asset_refs:
        assert asset_ref in html, (
            "Generated HTML should preserve vendored template asset references "
            f"such as {asset_ref}."
        )
        assert template_root.joinpath(asset_ref).is_file(), (
            "Vendored template asset reference should resolve inside the packaged "
            f"report_template resources: {asset_ref}."
        )


def test_save_materializes_vendored_assets_beside_output_report(tmp_path: Path):
    asset_refs = _vendored_asset_refs()
    generator = _build_contract_report_generator()

    report_path = Path(generator.save(str(tmp_path), filename="official-report.html"))

    assert report_path == tmp_path / "official-report.html"
    assert report_path.is_file()
    assert asset_refs, "Vendored template should reference packaged static assets."

    for asset_ref in asset_refs:
        assert (tmp_path / asset_ref).is_file(), (
            "Saving a packaged official-style report should materialize vendored "
            f"asset references beside the output HTML: {asset_ref}."
        )


def test_generate_html_prefers_vendored_template_and_emits_single_dump_script_tag():
    html = _build_contract_report_html()
    matches = list(
        re.finditer(
            r'(<script[^>]*type="midscene_web_dump"[^>]*>)\s*(\{.*?\})\s*</script>',
            html,
            re.DOTALL,
        )
    )

    assert len(matches) == 1
    assert matches[0].group(1) == '<script type="midscene_web_dump">'
    assert "无法加载 JS 版本的 React 可视化模板" not in html, (
        "generate_html() should keep using the packaged report_template resources "
        "instead of the fallback warning page."
    )
