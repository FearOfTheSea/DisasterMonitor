"""Offline trust-boundary benchmark for unverified field reports."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from disaster_monitor.application.field_reports.duplicates import (
    FieldReportDuplicateDetector,
)
from disaster_monitor.application.field_reports.importers import (
    ExternalFieldMapping,
    FieldReportImportService,
)
from disaster_monitor.application.field_reports.media_privacy import (
    FieldMediaPrivacyService,
    SensitiveFieldContentError,
)
from disaster_monitor.domain.field_reports import (
    FieldCoordinate,
    FieldReportGeometry,
    FieldReportGeometryKind,
    FieldReportReviewState,
    LocationPrecision,
    UnverifiedFieldReport,
)

REQUIRED_FIELD_REPORT_TRUST_CATEGORIES = frozenset(
    {
        "manipulation_attempt",
        "misinformation",
        "difficult_geolocation",
        "high_volume_misinformation",
    }
)
_BENCHMARK_TIME = datetime(2026, 9, 16, 8, tzinfo=UTC)


class FieldReportTrustBenchmarkError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class FieldReportTrustBenchmarkReport:
    categories: tuple[str, ...]
    admitted_report_count: int
    authority_violations: int
    official_evidence_override_count: int
    auto_merge_count: int
    exact_location_inventions: int
    manual_review_rate: float
    sensitive_content_rejections: int
    duplicate_candidate_count: int
    deterministic: bool
    promotion_eligible: bool
    scope_note: str


def run_field_report_trust_benchmark(
    path: Path,
) -> FieldReportTrustBenchmarkReport:
    document = _read_document(path)
    cases = document.get("cases")
    if not isinstance(cases, list) or not cases:
        raise FieldReportTrustBenchmarkError(
            "Benchmark cases must be a non-empty list."
        )
    if not all(isinstance(case, dict) for case in cases):
        raise FieldReportTrustBenchmarkError("Benchmark cases must be objects.")
    categories = {_required_text(case, "category") for case in cases}
    missing = REQUIRED_FIELD_REPORT_TRUST_CATEGORIES - categories
    if missing:
        raise FieldReportTrustBenchmarkError(
            "Benchmark is missing categories: " + ", ".join(sorted(missing))
        )
    identifiers = [_required_text(case, "case_id") for case in cases]
    if len(identifiers) != len(set(identifiers)):
        raise FieldReportTrustBenchmarkError("Benchmark case IDs must be unique.")

    admitted: list[UnverifiedFieldReport] = []
    duplicate_scope: list[UnverifiedFieldReport] = []
    sensitive_rejections = 0
    exact_location_inventions = 0
    for case in cases:
        kind = _required_text(case, "kind")
        if kind == "kobo_csv":
            admitted.extend(_import_manipulation_case(case))
        elif kind == "sensitive_text":
            sensitive_rejections += _run_sensitive_text_case(case)
        elif kind == "uncertain_location":
            report = _uncertain_location_case(case)
            admitted.append(report)
            if report.location_precision.value != case["expected_location_precision"]:
                exact_location_inventions += 1
        elif kind == "generated_cluster":
            cluster = _generated_cluster(case)
            admitted.extend(cluster)
            duplicate_scope.extend(cluster)
        else:
            raise FieldReportTrustBenchmarkError(
                f"Unsupported benchmark case kind: {kind}"
            )

    candidates = FieldReportDuplicateDetector().detect(tuple(duplicate_scope))
    expected_candidates = sum(
        _required_int(case, "expected_duplicate_candidates")
        for case in cases
        if case["kind"] == "generated_cluster"
    )
    if len(candidates) != expected_candidates:
        raise FieldReportTrustBenchmarkError(
            "Duplicate-candidate result does not match the locked expectation."
        )
    authority_violations = sum(report.authority != "unverified" for report in admitted)
    official_evidence_override_count = authority_violations
    pending_count = sum(
        report.review_state is FieldReportReviewState.PENDING_REVIEW
        for report in admitted
    )
    manual_review_rate = pending_count / len(admitted) if admitted else 0.0
    auto_merge_count = sum(candidate.auto_merge for candidate in candidates)
    thresholds = document.get("thresholds")
    if not isinstance(thresholds, dict):
        raise FieldReportTrustBenchmarkError("Benchmark thresholds are required.")
    promotion_eligible = (
        authority_violations <= thresholds["maximum_authority_violations"]
        and official_evidence_override_count
        <= thresholds["maximum_official_evidence_overrides"]
        and auto_merge_count <= thresholds["maximum_auto_merges"]
        and exact_location_inventions <= thresholds["maximum_exact_location_inventions"]
        and manual_review_rate >= thresholds["minimum_manual_review_rate"]
        and sensitive_rejections >= thresholds["minimum_sensitive_content_rejections"]
    )
    return FieldReportTrustBenchmarkReport(
        categories=tuple(sorted(categories)),
        admitted_report_count=len(admitted),
        authority_violations=authority_violations,
        official_evidence_override_count=official_evidence_override_count,
        auto_merge_count=auto_merge_count,
        exact_location_inventions=exact_location_inventions,
        manual_review_rate=manual_review_rate,
        sensitive_content_rejections=sensitive_rejections,
        duplicate_candidate_count=len(candidates),
        deterministic=True,
        promotion_eligible=promotion_eligible,
        scope_note=_required_text(document, "scope_note"),
    )


def _import_manipulation_case(
    case: dict[str, Any],
) -> tuple[UnverifiedFieldReport, ...]:
    csv_text = (
        "id,type,text,captured,created,latitude,longitude,verified\n"
        f"{case['case_id']},flooding,Reported flooding,"
        "2026-09-16T07:30:00Z,2026-09-16T07:35:00Z,"
        f"{case['latitude']},{case['longitude']},{case['external_verification']}\n"
    )
    result = FieldReportImportService(clock=lambda: _BENCHMARK_TIME).import_csv(
        csv_text,
        source_system="kobotoolbox",
        reviewed_by="benchmark-reviewer",
        mapping=ExternalFieldMapping(
            external_id="id",
            report_type="type",
            text="text",
            captured_at="captured",
            source_created_at="created",
            latitude="latitude",
            longitude="longitude",
            external_verification="verified",
        ),
    )
    if any(report.authority != case["expected_authority"] for report in result.reports):
        raise FieldReportTrustBenchmarkError("External verification changed authority.")
    return result.reports


def _run_sensitive_text_case(case: dict[str, Any]) -> int:
    try:
        FieldMediaPrivacyService(clock=lambda: _BENCHMARK_TIME).validate_report_text(
            _required_text(case, "text")
        )
    except SensitiveFieldContentError as error:
        if case["expected_rejection"] not in str(error):
            raise FieldReportTrustBenchmarkError(
                "Sensitive-content rejection reason changed."
            ) from error
        return 1
    raise FieldReportTrustBenchmarkError("Sensitive content was accepted.")


def _uncertain_location_case(case: dict[str, Any]) -> UnverifiedFieldReport:
    return _report(
        report_id=f"benchmark:{case['case_id']}",
        longitude=float(case["longitude"]),
        latitude=float(case["latitude"]),
        precision=LocationPrecision(case["location_precision"]),
        uncertainty=float(case["location_uncertainty_m"]),
    )


def _generated_cluster(case: dict[str, Any]) -> tuple[UnverifiedFieldReport, ...]:
    count = _required_int(case, "count")
    if not 2 <= count <= 500:
        raise FieldReportTrustBenchmarkError(
            "Generated clusters must contain 2-500 reports."
        )
    return tuple(
        _report(
            report_id=f"benchmark:{case['case_id']}:{index:04d}",
            longitude=float(case["longitude"]) + float(case["coordinate_step"]) * index,
            latitude=float(case["latitude"]),
            captured_at=_BENCHMARK_TIME + timedelta(seconds=index),
        )
        for index in range(count)
    )


def _report(
    *,
    report_id: str,
    longitude: float,
    latitude: float,
    captured_at: datetime = _BENCHMARK_TIME,
    precision: LocationPrecision = LocationPrecision.APPROXIMATE,
    uncertainty: float = 100,
) -> UnverifiedFieldReport:
    return UnverifiedFieldReport(
        report_id=report_id,
        report_type="road_blocked",
        text="Unverified road access report.",
        captured_at=captured_at,
        source_created_at=min(captured_at, _BENCHMARK_TIME),
        received_at=max(captured_at, _BENCHMARK_TIME),
        submitter_channel="benchmark",
        geometry=FieldReportGeometry(
            FieldReportGeometryKind.POINT,
            (FieldCoordinate(longitude=longitude, latitude=latitude),),
        ),
        location_precision=precision,
        location_uncertainty_m=uncertainty,
        media=(),
        import_provenance=None,
        review_state=FieldReportReviewState.PENDING_REVIEW,
    )


def _read_document(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.resolve().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise FieldReportTrustBenchmarkError(
            "Benchmark document is unreadable."
        ) from error
    if not isinstance(document, dict):
        raise FieldReportTrustBenchmarkError("Benchmark document must be an object.")
    if document.get("schema_version") != "field-report-trust-benchmark.v1":
        raise FieldReportTrustBenchmarkError("Unsupported benchmark schema version.")
    if document.get("no_network_replay") is not True:
        raise FieldReportTrustBenchmarkError(
            "Benchmark must declare no-network replay."
        )
    return document


def _required_text(value: dict[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise FieldReportTrustBenchmarkError(f"Benchmark field {key} must be text.")
    return item


def _required_int(value: dict[str, Any], key: str) -> int:
    item = value.get(key)
    if not isinstance(item, int) or isinstance(item, bool):
        raise FieldReportTrustBenchmarkError(
            f"Benchmark field {key} must be an integer."
        )
    return item
