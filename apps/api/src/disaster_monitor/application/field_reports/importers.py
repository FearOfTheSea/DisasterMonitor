"""Explicit-mapping imports for KoboToolbox, ODK, and Ushahidi records."""

from __future__ import annotations

import csv
import io
from collections.abc import Callable, Mapping
from dataclasses import dataclass, fields, replace
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

from disaster_monitor.domain.field_reports import (
    FieldCoordinate,
    FieldImportProvenance,
    FieldMediaLineage,
    FieldReportGeometry,
    FieldReportGeometryKind,
    FieldReportReviewState,
    LocationPrecision,
    UnverifiedFieldReport,
)


@dataclass(frozen=True, slots=True)
class ExternalFieldMapping:
    external_id: str
    report_type: str
    text: str
    captured_at: str
    source_created_at: str
    latitude: str
    longitude: str
    external_verification: str | None = None

    def __post_init__(self) -> None:
        required = (
            self.external_id,
            self.report_type,
            self.text,
            self.captured_at,
            self.source_created_at,
            self.latitude,
            self.longitude,
        )
        if any(not value.strip() for value in required):
            raise ValueError("Field imports require an explicit complete mapping.")

    def pairs(self) -> tuple[tuple[str, str], ...]:
        return tuple(
            (field.name, str(getattr(self, field.name)))
            for field in fields(self)
            if getattr(self, field.name) is not None
        )


@dataclass(frozen=True, slots=True)
class FieldReportImportResult:
    import_id: str
    source_system: str
    reports: tuple[UnverifiedFieldReport, ...]
    rejected_rows: tuple[str, ...]


class FieldReportImportService:
    def __init__(
        self,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        maximum_rows: int = 1_000,
    ) -> None:
        self._clock = clock
        self._maximum_rows = maximum_rows

    def import_csv(
        self,
        content: str,
        *,
        source_system: str,
        mapping: ExternalFieldMapping,
        reviewed_by: str,
        media_by_external_id: Mapping[str, tuple[FieldMediaLineage, ...]] | None = None,
    ) -> FieldReportImportResult:
        reader = csv.DictReader(io.StringIO(content))
        rows = list(reader)
        if len(rows) > self._maximum_rows:
            raise ValueError("Field-report import exceeds the row limit.")
        return self._import_rows(
            rows,
            source_system=source_system,
            mapping=mapping,
            reviewed_by=reviewed_by,
            media_by_external_id=media_by_external_id or {},
        )

    def import_geojson(
        self,
        document: Mapping[str, Any],
        *,
        source_system: str,
        mapping: ExternalFieldMapping,
        reviewed_by: str,
        media_by_external_id: Mapping[str, tuple[FieldMediaLineage, ...]] | None = None,
    ) -> FieldReportImportResult:
        features = document.get("features")
        if document.get("type") != "FeatureCollection" or not isinstance(
            features, list
        ):
            raise ValueError("Field-report GeoJSON must be a FeatureCollection.")
        if len(features) > self._maximum_rows:
            raise ValueError("Field-report import exceeds the row limit.")
        rows: list[dict[str, object]] = []
        for feature in features:
            if not isinstance(feature, dict) or not isinstance(
                feature.get("properties"), dict
            ):
                rows.append({})
                continue
            row = dict(feature["properties"])
            geometry = feature.get("geometry")
            if isinstance(geometry, dict) and geometry.get("type") == "Point":
                coordinates = geometry.get("coordinates")
                if isinstance(coordinates, list) and len(coordinates) >= 2:
                    row[mapping.longitude] = coordinates[0]
                    row[mapping.latitude] = coordinates[1]
            rows.append(row)
        return self._import_rows(
            rows,
            source_system=source_system,
            mapping=mapping,
            reviewed_by=reviewed_by,
            media_by_external_id=media_by_external_id or {},
        )

    def _import_rows(
        self,
        rows: list[dict[str, object]],
        *,
        source_system: str,
        mapping: ExternalFieldMapping,
        reviewed_by: str,
        media_by_external_id: Mapping[str, tuple[FieldMediaLineage, ...]],
    ) -> FieldReportImportResult:
        if source_system.casefold() not in {"kobotoolbox", "odk", "ushahidi"}:
            raise ValueError("Unsupported field-report import source.")
        if not reviewed_by.strip():
            raise ValueError("Field-report imports require reviewer attribution.")
        imported_at = self._clock()
        digest = sha256(
            f"{source_system}|{imported_at.isoformat()}|{len(rows)}".encode()
        ).hexdigest()[:24]
        import_id = f"field-import:{digest}"
        reports: list[UnverifiedFieldReport] = []
        rejected: list[str] = []
        for index, row in enumerate(rows, start=1):
            try:
                external_id = _required(row, mapping.external_id)
                captured_at = _timestamp(_required(row, mapping.captured_at))
                source_created_at = _timestamp(
                    _required(row, mapping.source_created_at)
                )
                longitude = float(_required(row, mapping.longitude))
                latitude = float(_required(row, mapping.latitude))
                verification = (
                    _optional(row, mapping.external_verification)
                    if mapping.external_verification
                    else None
                )
                identity = sha256(
                    f"{source_system}|{external_id}".encode()
                ).hexdigest()[:24]
                reports.append(
                    UnverifiedFieldReport(
                        report_id=f"field-report:{identity}",
                        report_type=_required(row, mapping.report_type),
                        text=_required(row, mapping.text),
                        captured_at=captured_at,
                        source_created_at=source_created_at,
                        received_at=imported_at,
                        submitter_channel=f"import:{source_system.casefold()}",
                        geometry=FieldReportGeometry(
                            FieldReportGeometryKind.POINT,
                            (FieldCoordinate(longitude, latitude),),
                        ),
                        location_precision=LocationPrecision.APPROXIMATE,
                        location_uncertainty_m=1_000,
                        media=media_by_external_id.get(external_id, ()),
                        import_provenance=FieldImportProvenance(
                            import_id=import_id,
                            source_system=source_system,
                            source_record_id=external_id,
                            imported_at=imported_at,
                            reviewed_by=reviewed_by.strip(),
                            field_mapping=mapping.pairs(),
                            external_verification=verification,
                        ),
                        review_state=FieldReportReviewState.PENDING_REVIEW,
                    )
                )
            except (TypeError, ValueError) as error:
                rejected.append(f"row {index}: {error}")
        return FieldReportImportResult(
            import_id, source_system, tuple(reports), tuple(rejected)
        )


class UshahidiMapper:
    def __init__(
        self, *, clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    ) -> None:
        self._clock = clock

    def import_posts(
        self, document: Mapping[str, Any], *, reviewed_by: str
    ) -> FieldReportImportResult:
        raw_results = document.get("results")
        if not isinstance(raw_results, list):
            raise ValueError("Ushahidi import requires a results list.")
        rows: list[dict[str, object]] = []
        categories_by_id: dict[str, tuple[str, ...]] = {}
        for raw in raw_results:
            if not isinstance(raw, dict):
                rows.append({})
                continue
            external_id = str(raw.get("id") or "")
            categories = tuple(
                str(item).strip()
                for item in raw.get("categories", [])
                if str(item).strip()
            )
            geometry = raw.get("geometry")
            coordinates = (
                geometry.get("coordinates") if isinstance(geometry, dict) else None
            )
            row = {
                "id": external_id,
                "kind": categories[0] if categories else "ushahidi_report",
                "text": " — ".join(
                    item
                    for item in (
                        str(raw.get("title") or "").strip(),
                        str(raw.get("content") or "").strip(),
                    )
                    if item
                ),
                "captured": raw.get("created"),
                "created": raw.get("created"),
                "longitude": coordinates[0] if isinstance(coordinates, list) else None,
                "latitude": coordinates[1] if isinstance(coordinates, list) else None,
                "verification": raw.get("status"),
            }
            rows.append(row)
            categories_by_id[external_id] = categories
        result = FieldReportImportService(clock=self._clock)._import_rows(
            rows,
            source_system="ushahidi",
            mapping=ExternalFieldMapping(
                external_id="id",
                report_type="kind",
                text="text",
                captured_at="captured",
                source_created_at="created",
                latitude="latitude",
                longitude="longitude",
                external_verification="verification",
            ),
            reviewed_by=reviewed_by,
            media_by_external_id={},
        )
        enriched = tuple(
            replace(
                report,
                tags=categories_by_id.get(
                    report.import_provenance.source_record_id, ()
                ),
            )
            if report.import_provenance is not None
            else report
            for report in result.reports
        )
        return FieldReportImportResult(
            result.import_id, result.source_system, enriched, result.rejected_rows
        )

    def export_posts(
        self, reports: tuple[UnverifiedFieldReport, ...]
    ) -> dict[str, object]:
        return {
            "results": [
                {
                    "id": report.report_id,
                    "title": report.report_type,
                    "content": report.text,
                    "created": report.source_created_at.isoformat(),
                    "verification_status": "unverified_by_disastermonitor",
                    "categories": list(report.tags or (report.report_type,)),
                    "geometry": {
                        "type": "Point",
                        "coordinates": [
                            report.geometry.centroid.longitude,
                            report.geometry.centroid.latitude,
                        ],
                    },
                }
                for report in reports
            ]
        }


def _required(row: Mapping[str, object], field: str) -> str:
    value = row.get(field)
    result = str(value).strip() if value is not None else ""
    if not result:
        raise ValueError(f"missing mapped field {field}")
    return result


def _optional(row: Mapping[str, object], field: str) -> str | None:
    value = row.get(field)
    result = str(value).strip() if value is not None else ""
    return result or None


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("mapped timestamps must include a timezone")
    return parsed
