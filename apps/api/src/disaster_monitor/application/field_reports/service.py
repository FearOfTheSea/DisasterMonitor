"""Submit, query, and review unverified field reports."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256

from disaster_monitor.application.field_reports.media_privacy import (
    FieldMediaPrivacyService,
)
from disaster_monitor.application.ports.field_reports import (
    FieldMediaStore,
    FieldReportStore,
)
from disaster_monitor.domain.field_reports import (
    FieldMediaLineage,
    FieldReportGeometry,
    FieldReportReview,
    FieldReportReviewDecision,
    FieldReportReviewOutcome,
    FieldReportReviewState,
    LocationPrecision,
    OperatorObservation,
    UnverifiedFieldReport,
    apply_field_report_review,
)


@dataclass(frozen=True, slots=True)
class NewFieldReport:
    report_type: str
    text: str
    captured_at: datetime
    source_created_at: datetime
    submitter_channel: str
    geometry: FieldReportGeometry
    location_precision: LocationPrecision
    location_uncertainty_m: float | None
    media: tuple[FieldMediaLineage, ...] = ()


class FieldReportNotFoundError(LookupError):
    pass


class FieldReportService:
    def __init__(
        self,
        store: FieldReportStore,
        *,
        privacy: FieldMediaPrivacyService | None = None,
        media_store: FieldMediaStore | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._store = store
        self._privacy = privacy
        self._media_store = media_store
        self._clock = clock

    async def submit(self, submission: NewFieldReport) -> UnverifiedFieldReport:
        received_at = self._clock()
        if self._privacy is not None:
            self._privacy.validate_report_text(submission.text)
        identity = sha256(
            "|".join(
                (
                    submission.report_type.strip().casefold(),
                    submission.text.strip(),
                    submission.captured_at.isoformat(),
                    submission.submitter_channel.strip(),
                    repr(submission.geometry),
                )
            ).encode()
        ).hexdigest()[:24]
        report = UnverifiedFieldReport(
            report_id=f"field-report:{identity}",
            report_type=submission.report_type.strip(),
            text=submission.text.strip(),
            captured_at=submission.captured_at,
            source_created_at=submission.source_created_at,
            received_at=received_at,
            submitter_channel=submission.submitter_channel.strip(),
            geometry=submission.geometry,
            location_precision=submission.location_precision,
            location_uncertainty_m=submission.location_uncertainty_m,
            media=submission.media,
            import_provenance=None,
            review_state=FieldReportReviewState.PENDING_REVIEW,
        )
        await self._store.add_report(report)
        return report

    def admit_media(
        self, *, filename: str, media_type: str, content: bytes
    ) -> FieldMediaLineage:
        if self._privacy is None or self._media_store is None:
            raise RuntimeError("Field-media persistence is not configured.")
        sanitized = self._privacy.sanitize(
            filename=filename, media_type=media_type, content=content
        )
        self._media_store.put(sanitized.lineage, sanitized.content)
        return sanitized.lineage

    async def import_reports(
        self, reports: tuple[UnverifiedFieldReport, ...]
    ) -> tuple[UnverifiedFieldReport, ...]:
        if self._privacy is not None:
            for report in reports:
                self._privacy.validate_report_text(report.text)
        for report in reports:
            await self._store.add_report(report)
        return reports

    async def list_queue(
        self, *, review_state: FieldReportReviewState | None = None, limit: int = 100
    ) -> tuple[UnverifiedFieldReport, ...]:
        return await self._store.reports(
            review_state=review_state.value if review_state else None,
            limit=limit,
        )

    async def review(
        self,
        report_id: str,
        decision: FieldReportReviewDecision,
        *,
        reviewer_id: str,
        rationale: str,
        event_id: str | None = None,
        authority_policy_id: str | None = None,
    ) -> FieldReportReviewOutcome:
        report = await self._store.report(report_id)
        if report is None:
            raise FieldReportNotFoundError(report_id)
        reviewed_at = self._clock()
        revision = report.review_revision + 1
        identity = sha256(
            f"{report_id}|{revision}|{decision.value}".encode()
        ).hexdigest()[:24]
        review = FieldReportReview(
            review_id=f"field-review:{identity}",
            report_id=report_id,
            decision=decision,
            reviewer_id=reviewer_id,
            rationale=rationale,
            reviewed_at=reviewed_at,
            event_id=event_id,
            authority_policy_id=authority_policy_id,
            revision=revision,
        )
        updated = apply_field_report_review(report, review)
        observation = (
            OperatorObservation(
                observation_id=f"operator-observation:{identity}",
                source_report_id=report_id,
                event_id=event_id or "",
                admitted_at=reviewed_at,
                admitted_by=reviewer_id,
                authority_policy_id=authority_policy_id or "",
            )
            if decision is FieldReportReviewDecision.ADMIT_OPERATOR_OBSERVATION
            else None
        )
        await self._store.record_review(updated, review, observation)
        return FieldReportReviewOutcome(updated, review, observation)
