"""Resolve reviewed terms while preserving authority identities."""

from disaster_monitor.application.ports.terminology import TerminologyPackReader
from disaster_monitor.domain.terminology import TerminologyPack


class TerminologyResolver:
    def __init__(self, reader: TerminologyPackReader) -> None:
        self._reader = reader

    def pack(self, language: str) -> TerminologyPack:
        return self._reader.read(language)

    def term(self, language: str, key: str) -> str:
        terms = dict(self.pack(language).terms)
        try:
            return terms[key]
        except KeyError as error:
            raise LookupError(f"Terminology key is not reviewed: {key}") from error

    def authority_name(self, language: str, authority_name: str) -> str:
        self.pack(language)
        return authority_name


__all__ = ["TerminologyResolver"]
