"""Derived provider freshness over retained evidence and attempt history."""

from datetime import datetime, timedelta

from disaster_monitor.domain.operations import (
    IngestJobStatus,
    ProviderAttemptOutcome,
    ProviderFreshness,
    current_attempt_diagnostics,
    freshness_for,
)
from disaster_monitor.infrastructure.operations.memory_evidence_port import (
    EvidenceMemoryPort,
)
from disaster_monitor.infrastructure.operations.memory_provider_news_port import (
    ProviderNewsMemoryPort,
)


class MemoryFreshnessQuery(EvidenceMemoryPort, ProviderNewsMemoryPort):
    async def freshness(
        self,
        *,
        now: datetime,
        expectations: dict[str, timedelta],
    ) -> tuple[ProviderFreshness, ...]:
        results: list[ProviderFreshness] = []
        for source_id, expectation in sorted(expectations.items()):
            snapshots = await self.snapshots(source_id=source_id, limit=1)
            attempts = await self.provider_attempts(source_id=source_id, limit=100)
            jobs = sorted(
                (item for item in self.jobs.values() if item.source_id == source_id),
                key=lambda item: (item.claimed_at or item.created_at, item.job_id),
                reverse=True,
            )
            last_job = jobs[0] if jobs else None
            last_attempt = attempts[0] if attempts else None
            consecutive = 0
            for attempt in attempts:
                if attempt.outcome not in {
                    ProviderAttemptOutcome.FAILED,
                    ProviderAttemptOutcome.INCOMPLETE,
                }:
                    break
                consecutive += 1
            if not attempts:
                for job in jobs:
                    if job.status not in {
                        IngestJobStatus.RETRY,
                        IngestJobStatus.DEAD_LETTER,
                    }:
                        break
                    consecutive += 1
            published_at = (
                snapshots[0].published_at
                if snapshots and snapshots[0].published_at is not None
                else last_attempt.published_at
                if last_attempt is not None
                else None
            )
            parse_failures, admission_failures, truncated, hazard = (
                current_attempt_diagnostics(attempts)
            )
            results.append(
                freshness_for(
                    source_id=source_id,
                    now=now,
                    expected_freshness=expectation,
                    last_attempt_at=(
                        last_attempt.attempted_at
                        if last_attempt is not None
                        else (
                            (last_job.claimed_at or last_job.created_at)
                            if last_job
                            else None
                        )
                    ),
                    last_snapshot=snapshots[0] if snapshots else None,
                    consecutive_failures=consecutive,
                    latest_error_code=(
                        last_attempt.reason_code
                        if last_attempt is not None
                        and last_attempt.outcome
                        in {
                            ProviderAttemptOutcome.FAILED,
                            ProviderAttemptOutcome.INCOMPLETE,
                        }
                        else last_job.last_error_code
                        if last_job
                        else None
                    ),
                    source_publication_age_seconds=(
                        max(0, int((now - published_at).total_seconds()))
                        if published_at is not None
                        else None
                    ),
                    retrieval_lag_seconds=(
                        max(
                            0,
                            int(
                                (
                                    snapshots[0].retrieved_at
                                    - snapshots[0].published_at
                                ).total_seconds()
                            ),
                        )
                        if snapshots and snapshots[0].published_at is not None
                        else None
                    ),
                    parse_failures=parse_failures,
                    admission_failures=admission_failures,
                    truncated=truncated,
                    hazard=hazard,
                )
            )
        return tuple(results)
