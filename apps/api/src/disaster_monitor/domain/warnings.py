"""Provider-neutral Common Alerting Protocol warning records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from disaster_monitor.domain.disaster_types import Disaster, _is_aware
from disaster_monitor.domain.hazards.taxonomy import DEFAULT_HAZARD_TAXONOMY
from disaster_monitor.domain.imagery.regions import Coordinate, MultiPolygon


class CapStatus(StrEnum):
    ACTUAL = "actual"
    EXERCISE = "exercise"
    SYSTEM = "system"
    TEST = "test"
    DRAFT = "draft"


class CapMessageType(StrEnum):
    ALERT = "alert"
    UPDATE = "update"
    CANCEL = "cancel"
    ACK = "ack"
    ERROR = "error"


class CapScope(StrEnum):
    PUBLIC = "public"
    RESTRICTED = "restricted"
    PRIVATE = "private"


class WarningSeverity(StrEnum):
    EXTREME = "extreme"
    SEVERE = "severe"
    MODERATE = "moderate"
    MINOR = "minor"
    UNKNOWN = "unknown"


class WarningUrgency(StrEnum):
    IMMEDIATE = "immediate"
    EXPECTED = "expected"
    FUTURE = "future"
    PAST = "past"
    UNKNOWN = "unknown"


class WarningCertainty(StrEnum):
    OBSERVED = "observed"
    LIKELY = "likely"
    POSSIBLE = "possible"
    UNLIKELY = "unlikely"
    UNKNOWN = "unknown"


class WarningLifecycleState(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class CapMessageReference:
    sender: str
    identifier: str
    sent: datetime

    def __post_init__(self) -> None:
        if (
            not self.sender.strip()
            or not self.identifier.strip()
            or not _is_aware(self.sent)
        ):
            raise ValueError(
                "CAP references require sender, identifier, and aware time."
            )

    @property
    def key(self) -> tuple[str, str, datetime]:
        return self.sender, self.identifier, self.sent


@dataclass(frozen=True, slots=True)
class CapCircle:
    center: Coordinate
    radius_km: float

    def __post_init__(self) -> None:
        if self.radius_km < 0:
            raise ValueError("CAP circle radii must be non-negative.")


@dataclass(frozen=True, slots=True)
class CapArea:
    description: str
    polygons: tuple[MultiPolygon, ...] = ()
    circles: tuple[CapCircle, ...] = ()
    geocodes: tuple[tuple[str, str], ...] = ()
    altitude_m: float | None = None
    ceiling_m: float | None = None

    def __post_init__(self) -> None:
        if not self.description.strip():
            raise ValueError("CAP areas require a source description.")
        if any(not name.strip() or not value.strip() for name, value in self.geocodes):
            raise ValueError("CAP geocodes require non-empty names and values.")


@dataclass(frozen=True, slots=True)
class CapInfo:
    language: str
    categories: tuple[str, ...]
    event: str
    event_codes: tuple[tuple[str, str], ...]
    urgency: WarningUrgency
    severity: WarningSeverity
    certainty: WarningCertainty
    effective: datetime | None
    onset: datetime | None
    expires: datetime | None
    sender_name: str | None
    headline: str | None
    description: str | None
    instruction: str | None
    areas: tuple[CapArea, ...]
    parameters: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not self.language.strip() or not self.event.strip() or not self.categories:
            raise ValueError("CAP info blocks require language, category, and event.")
        for value in (self.effective, self.onset, self.expires):
            if value is not None and not _is_aware(value):
                raise ValueError("CAP info timestamps must be timezone-aware.")
        if (
            self.expires is not None
            and self.effective is not None
            and self.expires < self.effective
        ):
            raise ValueError("CAP info expiry cannot precede its effective time.")


@dataclass(frozen=True, slots=True)
class CapAlert:
    identifier: str
    sender: str
    sent: datetime
    status: CapStatus
    message_type: CapMessageType
    scope: CapScope
    source_id: str
    publisher: str
    infos: tuple[CapInfo, ...]
    retrieved_at: datetime
    attribution: str
    limitations: tuple[str, ...]
    references: tuple[CapMessageReference, ...] = ()
    incidents: tuple[str, ...] = ()
    canonical_url: str | None = None
    source: str | None = None
    restriction: str | None = None
    addresses: tuple[str, ...] = ()
    codes: tuple[str, ...] = ()
    note: str | None = None
    profile: str | None = None
    signature_present: bool = False
    signature_verified: bool | None = None

    def __post_init__(self) -> None:
        required = (
            self.identifier,
            self.sender,
            self.source_id,
            self.publisher,
            self.attribution,
        )
        if any(not value.strip() for value in required):
            raise ValueError("CAP alerts require stable identity and attribution.")
        if not _is_aware(self.sent) or not _is_aware(self.retrieved_at):
            raise ValueError("CAP alert timestamps must be timezone-aware.")
        if self.scope is CapScope.RESTRICTED and not (self.restriction or "").strip():
            raise ValueError("Restricted CAP alerts require a restriction.")
        if self.scope is CapScope.PRIVATE and not self.addresses:
            raise ValueError("Private CAP alerts require addresses.")
        if self.canonical_url is not None and not self.canonical_url.startswith(
            "https://"
        ):
            raise ValueError("CAP canonical URLs must use HTTPS.")

    @property
    def message_key(self) -> tuple[str, str, datetime]:
        return self.sender, self.identifier, self.sent

    @property
    def hazard_candidates(self) -> tuple[Disaster, ...]:
        matches = {
            disaster
            for info in self.infos
            for text in (info.event, *(value for _, value in info.event_codes))
            if (disaster := DEFAULT_HAZARD_TAXONOMY.physical_disaster_for_warning(text))
            is not None
        }
        return tuple(sorted(matches, key=lambda item: item.value))


@dataclass(frozen=True, slots=True)
class ReconciledWarning:
    alert: CapAlert
    state: WarningLifecycleState
    superseded_identifiers: tuple[str, ...] = ()


__all__ = [
    name
    for name in globals()
    if name.startswith("Cap")
    or name.startswith("Warning")
    or name == "ReconciledWarning"
]
