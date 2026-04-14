"""Helpers for loading vendored report template package resources."""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any, cast

REPORT_TEMPLATE_PACKAGE = "pymidscene.resources.report_template"
REPORT_TEMPLATE_METADATA = "metadata.json"
REPORT_TEMPLATE_DEFAULT_ENTRYPOINT = "report.html"


@dataclass(frozen=True)
class ReportTemplateResources:
    """Vendored report template payload loaded from package resources."""

    metadata: dict[str, Any]
    html: str


def _report_template_root() -> Any:
    return resources.files(REPORT_TEMPLATE_PACKAGE)


def load_report_template_metadata() -> dict[str, Any]:
    metadata_path = _report_template_root() / REPORT_TEMPLATE_METADATA
    return cast(dict[str, Any], json.loads(metadata_path.read_text(encoding="utf-8")))


def load_report_template_html(metadata: dict[str, Any] | None = None) -> str:
    metadata = metadata or load_report_template_metadata()
    entrypoint = metadata.get(
        "template_entrypoint",
        REPORT_TEMPLATE_DEFAULT_ENTRYPOINT,
    )
    template_path = _report_template_root() / entrypoint
    return cast(str, template_path.read_text(encoding="utf-8"))


def load_report_template() -> ReportTemplateResources:
    metadata = load_report_template_metadata()
    return ReportTemplateResources(
        metadata=metadata,
        html=load_report_template_html(metadata),
    )


def _materialize_traversable_tree(source: Any, destination: Path) -> None:
    if source.is_dir():
        destination.mkdir(parents=True, exist_ok=True)
        for child in source.iterdir():
            _materialize_traversable_tree(child, destination / child.name)
        return

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(source.read_bytes())


def materialize_report_template_static_assets(output_dir: str | Path) -> None:
    static_root = _report_template_root() / "static"

    if not static_root.is_dir():
        return

    _materialize_traversable_tree(static_root, Path(output_dir) / "static")
