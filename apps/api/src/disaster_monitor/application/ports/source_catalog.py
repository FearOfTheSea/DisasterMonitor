"""Port for maintained source-intelligence metadata."""

from typing import Protocol

from disaster_monitor.application.agent.models import SourceDescriptor


class SourceCatalog(Protocol):
    @property
    def version(self) -> str: ...

    def sources(self) -> tuple[SourceDescriptor, ...]: ...

    def get(self, source_id: str) -> SourceDescriptor | None: ...
