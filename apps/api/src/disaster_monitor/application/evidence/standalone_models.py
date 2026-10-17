"""Independent section results for the desktop evidence surface."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from disaster_monitor.application.media import DisasterMediaGallery
from disaster_monitor.application.warnings.association import WarningAssociation
from disaster_monitor.domain.events import CycloneMapLayer
from disaster_monitor.domain.evidence import ReportedFact
from disaster_monitor.domain.exposure import ExposureAnalysis
from disaster_monitor.domain.hazard_context import BaselineVulnerabilityContext
from disaster_monitor.domain.humanitarian import HumanitarianContextSnapshot
from disaster_monitor.domain.reported_impacts import ReportedImpact
from disaster_monitor.domain.warnings import CapAlert

EvidenceSection = Literal[
    "impacts", "warnings", "forecast", "exposure", "humanitarian", "media"
]
EvidenceState = Literal["available", "empty", "unconfigured", "degraded", "error"]


@dataclass(frozen=True, slots=True)
class AssociatedWarning:
    alert: CapAlert
    association: WarningAssociation


@dataclass(frozen=True, slots=True)
class StandaloneEvidenceResult:
    event_id: str
    physical_event_id: str
    section: EvidenceSection
    state: EvidenceState
    retrieved_at: datetime
    limitations: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    facts: tuple[ReportedFact, ...] = ()
    narratives: tuple[str, ...] = ()
    forecast_layers: tuple[CycloneMapLayer, ...] = ()
    warnings: tuple[AssociatedWarning, ...] = ()
    exposure: ExposureAnalysis | None = None
    humanitarian: HumanitarianContextSnapshot | None = None
    baseline: BaselineVulnerabilityContext | None = None
    media: DisasterMediaGallery | None = None
    reported_accounts: tuple[ReportedImpact, ...] = ()
