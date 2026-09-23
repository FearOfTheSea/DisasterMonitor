"""Deterministic in-memory field-report repository."""

from disaster_monitor.domain.field_reports import (
    FieldReportReview,
    OperatorObservation,
    UnverifiedFieldReport,
)


class InMemoryFieldReportStore:
    def __init__(self) -> None:
        self._reports: dict[str, UnverifiedFieldReport] = {}
        self._reviews: dict[str, list[FieldReportReview]] = {}
        self.operator_observations: dict[str, OperatorObservation] = {}

    async def add_report(self, report: UnverifiedFieldReport) -> bool:
        existing = self._reports.get(report.report_id)
        if existing is not None:
            if existing != report:
                raise RuntimeError("Field-report identity was reused.")
            return False
        self._reports[report.report_id] = report
        return True

    async def add_reports(self, reports: tuple[UnverifiedFieldReport, ...]) -> None:
        updated = dict(self._reports)
        for report in reports:
            existing = updated.get(report.report_id)
            if existing is not None and existing != report:
                raise RuntimeError("Field-report identity was reused.")
            updated[report.report_id] = report
        self._reports = updated

    async def report(self, report_id: str) -> UnverifiedFieldReport | None:
        return self._reports.get(report_id)

    async def reports(
        self, *, review_state: str | None = None, limit: int = 100
    ) -> tuple[UnverifiedFieldReport, ...]:
        if not 1 <= limit <= 500:
            raise ValueError("Field-report limit must be between 1 and 500.")
        selected = (
            item
            for item in self._reports.values()
            if review_state is None or item.review_state.value == review_state
        )
        return tuple(
            sorted(
                selected,
                key=lambda item: (item.received_at, item.report_id),
                reverse=True,
            )[:limit]
        )

    async def record_review(
        self,
        report: UnverifiedFieldReport,
        review: FieldReportReview,
        observation: OperatorObservation | None,
    ) -> None:
        current = self._reports.get(report.report_id)
        if current is None:
            raise ValueError("Field report does not exist.")
        if current.review_revision + 1 != review.revision:
            raise RuntimeError("Field-report review revision is stale.")
        self._reports[report.report_id] = report
        self._reviews.setdefault(report.report_id, []).append(review)
        if observation is not None:
            self.operator_observations[observation.observation_id] = observation

    async def reviews(self, report_id: str) -> tuple[FieldReportReview, ...]:
        return tuple(self._reviews.get(report_id, ()))
