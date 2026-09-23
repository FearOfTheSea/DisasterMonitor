"""Submit, query, and review unverified field reports."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256

from disaster_monitor.application.field_reports.media_privacy import (
    FieldMediaPrivacyService,
    SanitizedFieldMedia,
)
from disaster_monitor.application.ports.field_reports import (
    CurrentIncidentVerifier,
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


class FieldReportEventNotFoundError(LookupError):
    pass


class IncidentEvidenceUnavailableError(RuntimeError):
    pass


class FieldReportConflictError(RuntimeError):
    pass


class FieldReportService:
    def __init__(
        self,
        store: FieldReportStore,
        *,
        privacy: FieldMediaPrivacyService | None = None,
        media_store: FieldMediaStore | None = None,
        event_verifier: CurrentIncidentVerifier | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._store = store
        self._privacy = privacy
        self._media_store = media_store
        self._event_verifier = event_verifier
        self._clock = clock
        self._write_lock = asyncio.Lock()

    def sanitize_media(
        self, *, filename: str, media_type: str, content: bytes
    ) -> SanitizedFieldMedia:
        if self._privacy is None or self._media_store is None:
            raise RuntimeError("Field-media persistence is not configured.")
        return self._privacy.sanitize(
            filename=filename, media_type=media_type, content=content
        )

    async def submit(self, submission: NewFieldReport) -> UnverifiedFieldReport:
        report, _ = await self.submit_with_media(submission)
        return report

    async def submit_with_media(
        self,
        submission: NewFieldReport,
        prepared_media: tuple[SanitizedFieldMedia, ...] = (),
    ) -> tuple[UnverifiedFieldReport, bool]:
        received_at = self._clock()
        if self._privacy is not None:
            self._privacy.validate_report_text(submission.text)
        media = tuple(item.lineage for item in prepared_media)
        if submission.media and prepared_media:
            raise ValueError("Field media was specified twice.")
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
            media=media or submission.media,
            import_provenance=None,
            review_state=FieldReportReviewState.PENDING_REVIEW,
        )
        async with self._write_lock:
            existing = await self._store.report(report.report_id)
            if existing is not None:
                if not _same_submission(existing, report):
                    raise FieldReportConflictError(
                        "Field-report identity was reused with conflicting content."
                    )
                return existing, False
            new_media_ids = self._publish_media(prepared_media)
            try:
                await self._store.add_report(report)
            except Exception:
                self._remove_new_media(new_media_ids)
                raise
            return report, True

    async def import_reports(
        self,
        reports: tuple[UnverifiedFieldReport, ...],
        prepared_media: tuple[SanitizedFieldMedia, ...] = (),
    ) -> tuple[UnverifiedFieldReport, ...]:
        if self._privacy is not None:
            for report in reports:
                self._privacy.validate_report_text(report.text)
        async with self._write_lock:
            new_media_ids = self._publish_media(prepared_media)
            try:
                await self._store.add_reports(reports)
            except Exception:
                self._remove_new_media(new_media_ids)
                raise
        return reports

    def _publish_media(self, media: tuple[SanitizedFieldMedia, ...]) -> tuple[str, ...]:
        if not media:
            return ()
        assert self._media_store is not None
        new_ids: list[str] = []
        try:
            for item in media:
                if self._media_store.get(item.lineage.media_id) is None:
                    new_ids.append(item.lineage.media_id)
                self._media_store.put(item.lineage, item.content)
        except Exception:
            self._remove_new_media(tuple(new_ids))
            raise
        return tuple(new_ids)

    def _remove_new_media(self, media_ids: tuple[str, ...]) -> None:
        if self._media_store is None:
            return
        for media_id in media_ids:
            self._media_store.delete(media_id)

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
        if decision in {
            FieldReportReviewDecision.ASSOCIATE_TO_EVENT,
            FieldReportReviewDecision.ADMIT_OPERATOR_OBSERVATION,
        }:
            if self._event_verifier is None:
                raise IncidentEvidenceUnavailableError(
                    "Current incident evidence is unavailable."
                )
            if not event_id or not await self._event_verifier.exists(event_id):
                raise FieldReportEventNotFoundError(event_id or "")
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


def _same_submission(
    existing: UnverifiedFieldReport, candidate: UnverifiedFieldReport
) -> bool:
    return (
        existing.report_type == candidate.report_type
        and existing.text == candidate.text
        and existing.captured_at == candidate.captured_at
        and existing.source_created_at == candidate.source_created_at
        and existing.submitter_channel == candidate.submitter_channel
        and existing.geometry == candidate.geometry
        and existing.location_precision == candidate.location_precision
        and existing.location_uncertainty_m == candidate.location_uncertainty_m
        and tuple(
            (item.original_filename, item.original_sha256) for item in existing.media
        )
        == tuple(
            (item.original_filename, item.original_sha256) for item in candidate.media
        )
    )
