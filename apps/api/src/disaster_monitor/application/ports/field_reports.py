"""Persistence seams for field reports and their review history."""

from typing import Protocol

from disaster_monitor.domain.field_reports import (
    FieldMediaLineage,
    FieldReportReview,
    OperatorObservation,
    UnverifiedFieldReport,
)


class FieldReportStore(Protocol):
    async def add_report(self, report: UnverifiedFieldReport) -> bool: ...

    async def add_reports(self, reports: tuple[UnverifiedFieldReport, ...]) -> None: ...

    async def report(self, report_id: str) -> UnverifiedFieldReport | None: ...

    async def reports(
        self, *, review_state: str | None = None, limit: int = 100
    ) -> tuple[UnverifiedFieldReport, ...]: ...

    async def record_review(
        self,
        report: UnverifiedFieldReport,
        review: FieldReportReview,
        observation: OperatorObservation | None,
    ) -> None: ...

    async def reviews(self, report_id: str) -> tuple[FieldReportReview, ...]: ...


class FieldMediaStore(Protocol):
    def put(self, lineage: FieldMediaLineage, content: bytes) -> None: ...

    def get(self, media_id: str) -> tuple[str, bytes] | None: ...

    def delete(self, media_id: str) -> None: ...


class CurrentIncidentVerifier(Protocol):
    async def exists(self, event_id: str) -> bool: ...
