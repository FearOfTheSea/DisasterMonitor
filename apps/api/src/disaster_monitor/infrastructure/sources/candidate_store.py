"""Request-independent in-memory store for non-authoritative source candidates."""

from disaster_monitor.application.source_intelligence import CandidateSourceRecord


class InMemoryCandidateSourceStore:
    def __init__(self) -> None:
        self._records: dict[str, CandidateSourceRecord] = {}

    def add(self, record: CandidateSourceRecord) -> None:
        candidate_id = record.submission.candidate_id
        if candidate_id in self._records:
            raise ValueError("A source candidate with this ID already exists.")
        self._records[candidate_id] = record

    def get(self, candidate_id: str) -> CandidateSourceRecord | None:
        return self._records.get(candidate_id)

    def candidates(self) -> tuple[CandidateSourceRecord, ...]:
        return tuple(self._records.values())
