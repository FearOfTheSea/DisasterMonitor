"""Admission contracts for normalized evidence returned by provider adapters."""

from typing import Protocol

from disaster_monitor.application.disaster import DisasterQuery
from disaster_monitor.domain.disaster import DisasterEvent, SituationReport


class SourceEvidencePolicyError(ValueError):
    """A normalized record escaped its approved source boundary."""


class EventEvidenceValidator(Protocol):
    def __call__(
        self,
        record: object,
        query: DisasterQuery,
        *,
        source_id: str,
        allowed_hosts: frozenset[str],
    ) -> DisasterEvent: ...


class SituationEvidenceValidator(Protocol):
    def __call__(
        self,
        record: object,
        query: DisasterQuery,
        *,
        source_id: str,
        allowed_hosts: frozenset[str],
    ) -> SituationReport: ...
