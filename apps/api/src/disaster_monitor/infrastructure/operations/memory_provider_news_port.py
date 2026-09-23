"""Deterministic in-memory operational repository for tests and safe fallback."""

from datetime import datetime

from disaster_monitor.domain.news import IncidentCandidate, NewsObservation
from disaster_monitor.domain.operations import (
    ProviderAttempt,
)
from disaster_monitor.domain.web_collection import WebFetchAudit, WebFetchState
from disaster_monitor.infrastructure.operations.memory_state import MemoryState


class ProviderNewsMemoryPort(MemoryState):
    async def read_web_fetch_state(self, source_id: str) -> WebFetchState | None:
        return self.web_fetch_states.get(source_id)

    async def save_web_fetch_state(self, state: WebFetchState) -> None:
        self.web_fetch_states[state.source_id] = state

    async def append_web_fetch_audit(self, audit: WebFetchAudit) -> bool:
        existing = self._web_fetch_audits.get(audit.audit_id)
        if existing is not None:
            if existing != audit:
                raise RuntimeError("Web fetch audit identity was reused.")
            return False
        self._web_fetch_audits[audit.audit_id] = audit
        return True

    async def web_fetch_audits(
        self, *, source_id: str, limit: int = 100
    ) -> tuple[WebFetchAudit, ...]:
        if not 1 <= limit <= 500:
            raise ValueError("Web fetch audit limit must be between 1 and 500.")
        return tuple(
            sorted(
                (
                    audit
                    for audit in self._web_fetch_audits.values()
                    if audit.source_id == source_id
                ),
                key=lambda audit: (audit.attempted_at, audit.audit_id),
                reverse=True,
            )[:limit]
        )

    async def record_provider_attempt(self, attempt: ProviderAttempt) -> None:
        records = self.provider_attempt_records.setdefault(attempt.source_id, [])
        records.append(attempt)
        records.sort(key=lambda item: item.attempted_at, reverse=True)
        del records[100:]

    async def provider_attempts(
        self, *, source_id: str, limit: int = 100
    ) -> tuple[ProviderAttempt, ...]:
        if not 1 <= limit <= 500:
            raise ValueError(
                "Provider attempt history limit must be between 1 and 500."
            )
        return tuple(self.provider_attempt_records.get(source_id, ())[:limit])

    async def append_news_observation(self, observation: NewsObservation) -> bool:
        existing = self.news_observations.get(observation.observation_id)
        if existing is not None:
            return False
        self.news_observations[observation.observation_id] = observation
        return True

    async def append_incident_candidate(self, candidate: IncidentCandidate) -> bool:
        existing = self.incident_candidate_revisions.get(candidate.revision_id)
        if existing is not None:
            if existing != candidate:
                raise RuntimeError("Incident candidate revision identity was reused.")
            return False
        self.incident_candidate_revisions[candidate.revision_id] = candidate
        return True

    async def latest_incident_candidates(
        self, *, since: datetime
    ) -> tuple[IncidentCandidate, ...]:
        latest: dict[str, IncidentCandidate] = {}
        for candidate in self.incident_candidate_revisions.values():
            if candidate.news_break_at < since:
                continue
            current = latest.get(candidate.candidate_id)
            if current is None or (
                candidate.candidate_created_at,
                candidate.revision_id,
            ) > (current.candidate_created_at, current.revision_id):
                latest[candidate.candidate_id] = candidate
        return tuple(
            sorted(
                latest.values(),
                key=lambda item: (item.news_break_at, item.candidate_id),
                reverse=True,
            )
        )
