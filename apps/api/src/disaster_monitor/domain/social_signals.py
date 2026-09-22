"""Untrusted public-signal records and operator labels."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from hashlib import sha256


def _require_aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware.")


class SignalCategory(StrEnum):
    HAZARD_REPORT = "hazard_report"
    INFRASTRUCTURE_DISRUPTION = "infrastructure_disruption"
    HUMANITARIAN_NEED = "humanitarian_need"
    NOT_RELEVANT = "not_relevant"


@dataclass(frozen=True, slots=True)
class SignalSourceTerms:
    source_id: str
    access_model: str
    terms_url: str
    reviewed_at: datetime
    redistribution_permitted: bool

    def __post_init__(self) -> None:
        if not self.source_id.strip():
            raise ValueError("Signal source terms require a source ID.")
        if self.access_model not in {"public", "self_hosted"}:
            raise ValueError("Signal sources must be public or self-hosted.")
        if not self.terms_url.startswith("https://"):
            raise ValueError("Signal source terms require an HTTPS URL.")
        _require_aware("reviewed_at", self.reviewed_at)


@dataclass(frozen=True, slots=True)
class UntrustedSocialSignal:
    signal_id: str
    source_id: str
    external_id: str
    text: str
    canonical_url: str
    published_at: datetime
    retrieved_at: datetime
    source_terms: SignalSourceTerms
    authority: str = "untrusted_signal"
    creates_physical_event: bool = False

    def __post_init__(self) -> None:
        if any(
            not value.strip()
            for value in (
                self.signal_id,
                self.source_id,
                self.external_id,
                self.text,
            )
        ):
            raise ValueError("Social signals require bounded identity and content.")
        if len(self.text) > 10_000:
            raise ValueError("Social signal text exceeds its bounded limit.")
        if not self.canonical_url.startswith("https://"):
            raise ValueError("Social signals require an HTTPS canonical URL.")
        if self.source_id != self.source_terms.source_id:
            raise ValueError("Signal source identity must match reviewed terms.")
        _require_aware("published_at", self.published_at)
        _require_aware("retrieved_at", self.retrieved_at)
        if self.retrieved_at < self.published_at:
            raise ValueError("A signal cannot be retrieved before publication.")
        if self.authority != "untrusted_signal" or self.creates_physical_event:
            raise ValueError("Social signals must remain untrusted discovery inputs.")


@dataclass(frozen=True, slots=True)
class OperatorSignalLabel:
    label_id: str
    signal_id: str
    signal_text: str
    reviewer_id: str
    category: SignalCategory
    labelled_at: datetime

    def __post_init__(self) -> None:
        if any(
            not value.strip()
            for value in (
                self.label_id,
                self.signal_id,
                self.signal_text,
                self.reviewer_id,
            )
        ):
            raise ValueError("Signal labels require signal and reviewer identity.")
        _require_aware("labelled_at", self.labelled_at)

    @classmethod
    def create(
        cls,
        *,
        signal: UntrustedSocialSignal,
        reviewer_id: str,
        category: SignalCategory,
        labelled_at: datetime,
    ) -> OperatorSignalLabel:
        material = "|".join(
            (signal.signal_id, reviewer_id, category.value, labelled_at.isoformat())
        )
        return cls(
            label_id=f"signal-label:{sha256(material.encode()).hexdigest()[:24]}",
            signal_id=signal.signal_id,
            signal_text=signal.text,
            reviewer_id=reviewer_id,
            category=category,
            labelled_at=labelled_at,
        )


@dataclass(frozen=True, slots=True)
class SignalClassification:
    signal_id: str
    category: SignalCategory
    relevance_score: float
    model_id: str
    model_version: str
    training_label_ids: tuple[str, ...]
    authority: str = "untrusted_signal"
    discovery_candidate: bool = True
    authority_changed: bool = False

    def __post_init__(self) -> None:
        if not 0 <= self.relevance_score <= 1:
            raise ValueError("Signal relevance scores must be bounded.")
        if not self.training_label_ids:
            raise ValueError(
                "Signal classification requires operator-labelled lineage."
            )
        if (
            self.authority != "untrusted_signal"
            or not self.discovery_candidate
            or self.authority_changed
        ):
            raise ValueError("Classification cannot change signal authority.")


__all__ = [
    "OperatorSignalLabel",
    "SignalCategory",
    "SignalClassification",
    "SignalSourceTerms",
    "UntrustedSocialSignal",
]
