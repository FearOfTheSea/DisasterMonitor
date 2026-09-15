"""Bounded screening for untrusted source candidates."""

import ipaddress
import re
from typing import Protocol
from urllib.parse import urlsplit

from disaster_monitor.application.agent.models import SourceInformationRole
from disaster_monitor.application.ports.candidate_source_store import (
    CandidateSourceStore,
)
from disaster_monitor.application.ports.source_catalog import SourceCatalog
from disaster_monitor.application.source_intelligence import (
    CandidateSourceInspection,
    CandidateSourceProbeResult,
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
        if not submission.disasters:
            risk_flags.append("no_supported_disaster")
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


class CandidateSourceProbe(Protocol):
    async def inspect(
        self, homepage_url: str, *, license_url: str | None
    ) -> CandidateSourceProbeResult: ...


class SourceCandidateWorkbench:
    """Run bounded technical checks while keeping promotion a human decision."""

    def __init__(self, scout: SourceScout, probe: CandidateSourceProbe) -> None:
        self._scout = scout
        self._probe = probe

    async def inspect(
        self, submission: CandidateSourceSubmission
    ) -> CandidateSourceInspection:
        record = self._scout.assess(submission)
        if record.status is CandidateSourceStatus.REJECTED:
            return CandidateSourceInspection(
                record, None, False, False, False, record.risk_flags
            )
        probe = await self._probe.inspect(
            submission.homepage_url, license_url=submission.license_url
        )
        expected = set(submission.expected_fields)
        schema_matches = bool(expected) and expected <= set(probe.top_level_fields)
        findings: list[str] = []
        if not probe.reachable or probe.status_code != 200:
            findings.append("endpoint_unreachable")
        if not schema_matches:
            findings.append("schema_shape_unconfirmed")
        if not probe.license_reachable:
            findings.append("license_terms_unavailable")
        return CandidateSourceInspection(
            record=record,
            probe=probe,
            schema_matches=schema_matches,
            license_terms_available=probe.license_reachable,
            ready_for_human_review=not findings,
            findings=tuple(findings),
        )


def _roles_for(signals: tuple[str, ...]) -> tuple[SourceInformationRole, ...]:
    roles = [role for signal in signals for role in _SIGNAL_ROLES.get(signal, ())]
    return tuple(dict.fromkeys(roles))
