"""Typed artifacts kept outside trusted disaster evidence."""

from dataclasses import dataclass
from enum import StrEnum

from disaster_monitor.application.agent.models import SourceInformationRole
from disaster_monitor.domain.disaster import Disaster


class CandidateSourceStatus(StrEnum):
    AWAITING_HUMAN_APPROVAL = "awaiting_human_approval"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class CandidateSourceSubmission:
    candidate_id: str
    display_name: str
    homepage_url: str
    content_signals: tuple[str, ...]
    disasters: tuple[Disaster, ...]
    country_codes: tuple[str, ...] | None = None
    claimed_organization: str = ""
    claimed_domain: str | None = None
    claimed_authority: str | None = None
    expected_fields: tuple[str, ...] = ()
    license_url: str | None = None


@dataclass(frozen=True, slots=True)
class CandidateSourceRecord:
    submission: CandidateSourceSubmission
    status: CandidateSourceStatus
    inferred_roles: tuple[SourceInformationRole, ...]
    risk_flags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CandidateSourceProbeResult:
    reachable: bool
    status_code: int | None
    content_type: str | None
    top_level_fields: tuple[str, ...]
    license_reachable: bool
    checked_url: str


@dataclass(frozen=True, slots=True)
class CandidateSourceInspection:
    record: CandidateSourceRecord
    probe: CandidateSourceProbeResult | None
    schema_matches: bool
    license_terms_available: bool
    ready_for_human_review: bool
    findings: tuple[str, ...]
