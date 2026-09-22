"""Machine-checkable rights contracts for source and imagery providers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class AccessModel(StrEnum):
    """The entitlement needed to use a provider in production."""

    PUBLIC = "public"
    FREE_ACCOUNT = "free_account"
    SELF_HOSTED = "self_hosted"
    PAID = "paid"


@dataclass(frozen=True, slots=True)
class ProviderRights:
    """Machine-checkable rights and retention terms for one source or layer."""

    asset_id: str
    authority: str
    license_name: str
    attribution_text: str
    redistribution_policy: str
    cache_policy: str
    rate_limit_policy: str
    credential_class: str
    retention_limit_days: int
    last_human_review: date
    access_model: AccessModel
    production: bool = True

    def __post_init__(self) -> None:
        if not self.asset_id.strip() or not self.authority.strip():
            raise ValueError("Provider rights require a stable asset and authority.")
        required = (
            self.license_name,
            self.attribution_text,
            self.redistribution_policy,
            self.cache_policy,
            self.rate_limit_policy,
            self.credential_class,
        )
        if any(not value.strip() for value in required):
            raise ValueError("Provider rights metadata cannot be blank.")
        if self.retention_limit_days < 1:
            raise ValueError("Provider retention limits must be positive.")


@dataclass(frozen=True, slots=True)
class ProviderRightsManifest:
    """Versioned rights manifest with fail-closed production validation."""

    schema_version: str
    version: str
    entries: tuple[ProviderRights, ...]

    def __post_init__(self) -> None:
        identifiers = [entry.asset_id for entry in self.entries]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("Provider-rights asset IDs must be unique.")

    def get(self, asset_id: str) -> ProviderRights | None:
        return next((item for item in self.entries if item.asset_id == asset_id), None)

    def validate_production(self, *, today: date) -> None:
        """Reject missing, expired, or commercial production entitlements."""
        annual_review_boundary = _previous_year_boundary(today)
        for entry in self.entries:
            if entry.production and entry.access_model is AccessModel.PAID:
                raise ValueError(
                    f"Paid provider {entry.asset_id} cannot be a production dependency."
                )
            if entry.last_human_review > today:
                raise ValueError(
                    f"Provider-rights review for {entry.asset_id} is in the future."
                )
            if entry.last_human_review < annual_review_boundary:
                raise ValueError(
                    f"Provider-rights review for {entry.asset_id} has expired."
                )

    def require_all(self, asset_ids: tuple[str, ...] | list[str]) -> None:
        """Fail closed when a registered source or layer is absent from the manifest."""
        missing = sorted(set(asset_ids) - {entry.asset_id for entry in self.entries})
        if missing:
            raise ValueError(
                "Provider-rights metadata is missing for: " + ", ".join(missing)
            )


def _previous_year_boundary(today: date) -> date:
    try:
        return today.replace(year=today.year - 1)
    except ValueError:
        return date(today.year - 1, 2, 28)
