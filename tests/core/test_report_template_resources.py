"""Tests for vendored report template package resources."""

import importlib
import json
from importlib import resources
from unittest.mock import patch

REPORT_TEMPLATE_PACKAGE = "pymidscene.resources.report_template"


def _report_template_root():
    try:
        return resources.files(REPORT_TEMPLATE_PACKAGE)
    except ModuleNotFoundError as exc:
        raise AssertionError(
            "Vendored report template package is missing: " f"{REPORT_TEMPLATE_PACKAGE}."
        ) from exc


def test_vendored_report_template_layout_matches_the_approved_resource_spec():
    template_root = _report_template_root()
    asset_names = sorted(entry.name for entry in template_root.iterdir())

    assert "report.html" in asset_names, (
        "Expected the vendored report shell to be packaged as "
        f"{REPORT_TEMPLATE_PACKAGE}/report.html."
    )
    assert "metadata.json" in asset_names, (
        "Expected vendored report metadata to be packaged as "
        f"{REPORT_TEMPLATE_PACKAGE}/metadata.json."
    )


def test_vendored_report_template_metadata_points_at_report_html():
    template_root = _report_template_root()
    metadata_path = template_root / "metadata.json"

    assert metadata_path.is_file(), "Missing vendored report template metadata file."

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata_text = json.dumps(metadata, ensure_ascii=False)

    assert "report.html" in metadata_text, (
        "Vendored report template metadata should reference the packaged " "report.html shell."
    )


def test_core_loader_reads_vendored_report_template_from_package_resources():
    try:
        loader_module = importlib.import_module("pymidscene.core.report_template_resources")
    except ModuleNotFoundError as exc:
        raise AssertionError(
            "Expected pymidscene.core.report_template_resources to expose "
            "the package-resource report template loader."
        ) from exc

    report_template = loader_module.load_report_template()

    assert report_template.metadata["template_entrypoint"] == "report.html"
    assert '<div id="root"' in report_template.html


def test_js_react_report_generator_loads_packaged_template_without_local_path_scanning():
    from pymidscene.core.js_react_report_generator import JSReactReportGenerator

    generator = JSReactReportGenerator()
    generator._js_template = None
    JSReactReportGenerator._js_template_cache = None

    with patch(
        "glob.glob",
        side_effect=AssertionError("Local report file globbing should not run."),
    ):
        template = generator._load_js_template()

    assert template is not None
    assert '<div id="root"' in template
