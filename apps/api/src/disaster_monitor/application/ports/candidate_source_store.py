"""Port for source candidates that have no evidence authority."""

from typing import Protocol

from disaster_monitor.application.source_intelligence import CandidateSourceRecord


class CandidateSourceStore(Protocol):
    def add(self, record: CandidateSourceRecord) -> None: ...

    def get(self, candidate_id: str) -> CandidateSourceRecord | None: ...

    def candidates(self) -> tuple[CandidateSourceRecord, ...]: ...
