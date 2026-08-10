"""Bounded screening for untrusted source candidates."""

import ipaddress
import re
from urllib.parse import urlsplit

from disaster_monitor.application.agent.models import SourceInformationRole
from disaster_monitor.application.ports.candidate_source_store import (
    CandidateSourceStore,
)
from disaster_monitor.application.ports.source_catalog import SourceCatalog
from disaster_monitor.application.source_intelligence import (
    CandidateSourceRecord,
    CandidateSourceStatus,
    CandidateSourceSubmission,
)

_COUNTRY_CODE = re.compile(r"^[A-Z]{3}$")
_FREE_HOSTS = ("github.io", "pages.dev", "blogspot.com", "wordpress.com")
_SIGNAL_ROLES = {
    "event_feed": (
        SourceInformationRole.EVENT_DISCOVERY,
        SourceInformationRole.SCIENTIFIC_EVENT_VERIFICATION,
    ),
    "official_warning": (SourceInformationRole.OFFICIAL_WARNING,),
    "casualty_reporting": (SourceInformationRole.CASUALTY_REPORTING,),
    "physical_damage": (SourceInformationRole.PHYSICAL_DAMAGE,),
    "infrastructure_status": (SourceInformationRole.INFRASTRUCTURE_STATUS,),
    "emergency_response": (SourceInformationRole.EMERGENCY_RESPONSE,),
    "situation_report": (SourceInformationRole.HUMANITARIAN_REPORTING,),
    "tsunami_status": (SourceInformationRole.TSUNAMI_STATUS,),
}


class SourceScout:
    def __init__(
        self, trusted_catalog: SourceCatalog, candidate_store: CandidateSourceStore
    ) -> None:
        self._trusted_catalog = trusted_catalog
        self._candidate_store = candidate_store

    def assess(self, submission: CandidateSourceSubmission) -> CandidateSourceRecord:
        roles = _roles_for(submission.content_signals)
        risk_flags = list(self._url_risks(submission))
        if not submission.candidate_id.strip() or not submission.display_name.strip():
            risk_flags.append("invalid_identity")
        if not roles:
            risk_flags.append("no_supported_information_role")
        if not submission.hazards:
            risk_flags.append("no_supported_hazard")
        if submission.country_codes is not None and any(
            not _COUNTRY_CODE.fullmatch(code) for code in submission.country_codes
        ):
            risk_flags.append("invalid_country_scope")
        status = (
            CandidateSourceStatus.REJECTED
            if risk_flags
            else CandidateSourceStatus.AWAITING_HUMAN_APPROVAL
        )
        record = CandidateSourceRecord(
            submission,
            status,
            roles,
            tuple(dict.fromkeys(risk_flags)),
        )
        self._candidate_store.add(record)
        return record

    def _url_risks(self, submission: CandidateSourceSubmission) -> tuple[str, ...]:
        try:
            target = urlsplit(submission.homepage_url)
            port = target.port
            hostname = (target.hostname or "").lower().rstrip(".")
            address = ipaddress.ip_address(hostname)
        except ValueError:
            address = None
            try:
                target = urlsplit(submission.homepage_url)
                port = target.port
                hostname = (target.hostname or "").lower().rstrip(".")
            except ValueError:
                return ("invalid_url",)
        risks: list[str] = []
        if (
            target.scheme.lower() != "https"
            or not hostname
            or target.username is not None
            or target.password is not None
            or port not in {None, 443}
        ):
            risks.append("unsafe_url")
        if (
            address is not None
            or hostname == "localhost"
            or hostname.endswith(".local")
        ):
            risks.append("non_public_host")
        if hostname.startswith("xn--") or ".xn--" in hostname:
            risks.append("idn_domain_requires_review")
        if submission.claimed_domain:
            claimed = submission.claimed_domain.lower().rstrip(".")
            if hostname != claimed and not hostname.endswith(f".{claimed}"):
                risks.append("claimed_domain_mismatch")
        trusted_hosts = {
            host.lower().rstrip(".")
            for source in self._trusted_catalog.sources()
            for host in source.allowed_hosts
        }
        if any(
            trusted in hostname
            and hostname != trusted
            and not hostname.endswith(f".{trusted}")
            for trusted in trusted_hosts
        ):
            risks.append("authority_domain_spoof")
        if submission.claimed_authority and any(
            hostname == suffix or hostname.endswith(f".{suffix}")
            for suffix in _FREE_HOSTS
        ):
            risks.append("authority_claim_on_shared_host")
        return tuple(risks)


def _roles_for(signals: tuple[str, ...]) -> tuple[SourceInformationRole, ...]:
    roles = [role for signal in signals for role in _SIGNAL_ROLES.get(signal, ())]
    return tuple(dict.fromkeys(roles))
