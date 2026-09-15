"""Credential-free Ground comparison export bundles."""

import json
import zipfile
from pathlib import Path

from disaster_monitor.application.ground_imagery.comparisons import (
    GroundComparisonManifest,
    comparison_document,
)
from disaster_monitor.domain.imagery.regions import MultiPolygon


class GroundExportBundleBuilder:
    def build(
        self,
        *,
        output_path: Path,
        incident_id: str,
        region: MultiPolygon,
        comparison: GroundComparisonManifest,
        cogs: tuple[Path, ...],
        previews: tuple[Path, ...],
    ) -> Path:
        artifacts = (*cogs, *previews)
        if any(not path.is_file() for path in artifacts):
            raise ValueError("Every Ground export artifact must be an existing file.")
        names = [path.name for path in artifacts]
        if len(names) != len(set(names)):
            raise ValueError("Ground export artifact filenames must be unique.")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        readme = {
            "bundle_version": "ground-export-bundle-v1",
            "incident_id": incident_id,
            "comparison_id": comparison.comparison_id,
            "region_sha256": region.sha256(),
            "credentials_included": False,
            "contents": {
                "cogs": [path.name for path in cogs],
                "previews": [path.name for path in previews],
            },
        }
        with zipfile.ZipFile(
            output_path, "w", compression=zipfile.ZIP_DEFLATED
        ) as archive:
            for path in cogs:
                _write(archive, f"cogs/{path.name}", path.read_bytes())
            for path in previews:
                _write(archive, f"previews/{path.name}", path.read_bytes())
            _write_json(archive, "region.geojson", region.as_geojson())
            _write_json(
                archive,
                "comparison-manifest.json",
                comparison_document(comparison),
            )
            _write_json(archive, "README.json", readme)
        return output_path


def _write_json(
    archive: zipfile.ZipFile, name: str, document: dict[str, object]
) -> None:
    _write(
        archive,
        name,
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode(),
    )


def _write(archive: zipfile.ZipFile, name: str, content: bytes) -> None:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o600 << 16
    archive.writestr(info, content)
