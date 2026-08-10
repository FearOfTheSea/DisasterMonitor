"""Typed artifacts kept outside trusted disaster evidence."""

from dataclasses import dataclass
from enum import StrEnum

from disaster_monitor.application.agent.models import SourceInformationRole
from disaster_monitor.domain.disaster import Hazard


class CandidateSourceStatus(StrEnum):
    AWAITING_HUMAN_APPROVAL = "awaiting_human_approval"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class CandidateSourceSubmission:
    candidate_id: str
    display_name: str
    homepage_url: str
    content_signals: tuple[str, ...]
    hazards: tuple[Hazard, ...]
    country_codes: tuple[str, ...] | None = None
    claimed_organization: str = ""
    claimed_domain: str | None = None
    claimed_authority: str | None = None


@dataclass(frozen=True, slots=True)
class CandidateSourceRecord:
    submission: CandidateSourceSubmission
    status: CandidateSourceStatus
    inferred_roles: tuple[SourceInformationRole, ...]
    risk_flags: tuple[str, ...]
