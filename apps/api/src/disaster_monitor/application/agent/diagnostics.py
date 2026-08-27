"""Typed low-cardinality diagnostics for optional agent capabilities."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class AgentCapability(StrEnum):
    EVENT_MEDIA_DISCOVERY = "event_media_discovery"
    RESPONSE_LOCALIZATION = "response_localization"


class AgentCapabilityFailure(StrEnum):
    DEPENDENCY_FAILURE = "dependency_failure"
    INVALID_RESULT = "invalid_result"
    NOT_SUPPORTED = "not_supported"


@dataclass(frozen=True, slots=True)
class AgentCapabilityDiagnostic:
    capability: AgentCapability
    failure: AgentCapabilityFailure
    attempt_count: int
    exception_type: str | None = None


class AgentDiagnostics(Protocol):
    def record(self, diagnostic: AgentCapabilityDiagnostic) -> None: ...
