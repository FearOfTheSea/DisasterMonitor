"""Durable local repository for field reports and review history."""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from disaster_monitor.domain.field_reports import (
    FieldCoordinate,
    FieldImportProvenance,
    FieldMediaLineage,
    FieldReportGeometry,
    FieldReportGeometryKind,
    FieldReportReview,
    FieldReportReviewDecision,
    FieldReportReviewState,
    LocationPrecision,
    OperatorObservation,
    UnverifiedFieldReport,
)


class JsonFieldReportStore:
    def __init__(self, path: Path, *, maximum_reports: int = 10_000) -> None:
        if maximum_reports <= 0:
            raise ValueError("Field-report capacity must be positive.")
        self._path = path.resolve()
        self._maximum_reports = maximum_reports
        self._lock = asyncio.Lock()
        self._reports: dict[str, UnverifiedFieldReport] = {}
        self._reviews: dict[str, list[FieldReportReview]] = {}
        self._observations: dict[str, OperatorObservation] = {}
        self._load()

    async def add_report(self, report: UnverifiedFieldReport) -> bool:
        async with self._lock:
            existing = self._reports.get(report.report_id)
            if existing is not None:
                if existing != report:
                    raise RuntimeError("Field-report identity was reused.")
                return False
            if len(self._reports) >= self._maximum_reports:
                raise ValueError("Field-report storage has reached its record limit.")
            self._reports[report.report_id] = report
            self._persist()
            return True

    async def report(self, report_id: str) -> UnverifiedFieldReport | None:
        return self._reports.get(report_id)

    async def reports(
        self, *, review_state: str | None = None, limit: int = 100
    ) -> tuple[UnverifiedFieldReport, ...]:
        if not 1 <= limit <= 500:
            raise ValueError("Field-report limit must be between 1 and 500.")
        selected = (
            report
            for report in self._reports.values()
            if review_state is None or report.review_state.value == review_state
        )
        return tuple(
            sorted(
                selected,
                key=lambda report: (report.received_at, report.report_id),
                reverse=True,
            )[:limit]
        )

    async def record_review(
        self,
        report: UnverifiedFieldReport,
        review: FieldReportReview,
        observation: OperatorObservation | None,
    ) -> None:
        async with self._lock:
            current = self._reports.get(report.report_id)
            if current is None:
                raise ValueError("Field report does not exist.")
            if current.review_revision + 1 != review.revision:
                raise RuntimeError("Field-report review revision is stale.")
            self._reports[report.report_id] = report
            self._reviews.setdefault(report.report_id, []).append(review)
            if observation is not None:
                self._observations[observation.observation_id] = observation
            self._persist()

    async def reviews(self, report_id: str) -> tuple[FieldReportReview, ...]:
        return tuple(self._reviews.get(report_id, ()))

    def _load(self) -> None:
        if not self._path.is_file():
            return
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        if raw.get("schema_version") != "field-report-store.v1":
            raise ValueError("Unsupported field-report store schema.")
        self._reports = {
            item["report_id"]: _report_from_dict(item)
            for item in raw.get("reports", [])
        }
        self._reviews = {}
        for item in raw.get("reviews", []):
            review = _review_from_dict(item)
            self._reviews.setdefault(review.report_id, []).append(review)
        self._observations = {
            item["observation_id"]: _observation_from_dict(item)
            for item in raw.get("operator_observations", [])
        }

    def _persist(self) -> None:
        document: dict[str, object] = {
            "schema_version": "field-report-store.v1",
            "reports": [_json_value(asdict(item)) for item in self._reports.values()],
            "reviews": [
                _json_value(asdict(review))
                for reviews in self._reviews.values()
                for review in reviews
            ],
            "operator_observations": [
                _json_value(asdict(item)) for item in self._observations.values()
            ],
        }
        _atomic_json_write(self._path, document)


def _report_from_dict(raw: dict[str, Any]) -> UnverifiedFieldReport:
    geometry = raw["geometry"]
    provenance = raw.get("import_provenance")
    return UnverifiedFieldReport(
        report_id=raw["report_id"],
        report_type=raw["report_type"],
        text=raw["text"],
        captured_at=datetime.fromisoformat(raw["captured_at"]),
        source_created_at=datetime.fromisoformat(raw["source_created_at"]),
        received_at=datetime.fromisoformat(raw["received_at"]),
        submitter_channel=raw["submitter_channel"],
        geometry=FieldReportGeometry(
            kind=FieldReportGeometryKind(geometry["kind"]),
            coordinates=tuple(
                FieldCoordinate(**coordinate) for coordinate in geometry["coordinates"]
            ),
        ),
        location_precision=LocationPrecision(raw["location_precision"]),
        location_uncertainty_m=raw.get("location_uncertainty_m"),
        media=tuple(_media_from_dict(item) for item in raw.get("media", [])),
        import_provenance=(
            _provenance_from_dict(provenance) if provenance is not None else None
        ),
        review_state=FieldReportReviewState(raw["review_state"]),
        authority=raw["authority"],
        tags=tuple(raw.get("tags", [])),
        associated_event_id=raw.get("associated_event_id"),
        review_revision=raw.get("review_revision", 0),
    )


def _media_from_dict(raw: dict[str, Any]) -> FieldMediaLineage:
    return FieldMediaLineage(
        media_id=raw["media_id"],
        original_filename=raw["original_filename"],
        media_type=raw["media_type"],
        original_sha256=raw["original_sha256"],
        stored_sha256=raw["stored_sha256"],
        byte_length=raw["byte_length"],
        transformations=tuple(raw["transformations"]),
        retention_expires_at=datetime.fromisoformat(raw["retention_expires_at"]),
    )


def _provenance_from_dict(raw: dict[str, Any]) -> FieldImportProvenance:
    return FieldImportProvenance(
        import_id=raw["import_id"],
        source_system=raw["source_system"],
        source_record_id=raw["source_record_id"],
        imported_at=datetime.fromisoformat(raw["imported_at"]),
        reviewed_by=raw["reviewed_by"],
        field_mapping=tuple(tuple(item) for item in raw["field_mapping"]),
        external_verification=raw.get("external_verification"),
        verification_inherited=raw.get("verification_inherited", False),
    )


def _review_from_dict(raw: dict[str, Any]) -> FieldReportReview:
    return FieldReportReview(
        review_id=raw["review_id"],
        report_id=raw["report_id"],
        decision=FieldReportReviewDecision(raw["decision"]),
        reviewer_id=raw["reviewer_id"],
        rationale=raw["rationale"],
        reviewed_at=datetime.fromisoformat(raw["reviewed_at"]),
        event_id=raw.get("event_id"),
        authority_policy_id=raw.get("authority_policy_id"),
        revision=raw["revision"],
    )


def _observation_from_dict(raw: dict[str, Any]) -> OperatorObservation:
    return OperatorObservation(
        observation_id=raw["observation_id"],
        source_report_id=raw["source_report_id"],
        event_id=raw["event_id"],
        admitted_at=datetime.fromisoformat(raw["admitted_at"]),
        admitted_by=raw["admitted_by"],
        authority_policy_id=raw["authority_policy_id"],
        authority=raw["authority"],
    )


def _json_value(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _atomic_json_write(path: Path, document: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(document, stream, ensure_ascii=False, separators=(",", ":"))
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(temporary, 0o600)
    temporary.replace(path)
