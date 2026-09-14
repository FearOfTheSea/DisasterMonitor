from datetime import date, timedelta

import pytest

from disaster_monitor.application.ports.provider_rights import (
    AccessModel,
    ProviderRights,
    ProviderRightsManifest,
)
from disaster_monitor.infrastructure.satellite_imagery.providers import (
    NasaGibsImageryProvider,
)
from disaster_monitor.infrastructure.sources.provider_rights_manifest import (
    load_provider_rights_manifest,
)
from disaster_monitor.infrastructure.sources.static_source_catalog import (
    StaticSourceCatalog,
)


def test_packaged_rights_cover_sources_and_supported_layers() -> None:
    manifest = load_provider_rights_manifest()
    source_ids = {item.source_id for item in StaticSourceCatalog().sources()}
    imagery_ids = {product.rights_id for product in NasaGibsImageryProvider().products}

    manifest.require_all(
        sorted(
            source_ids
            | imagery_ids
            | {"nasa-gibs", "copernicus-data-space-ground", "open-cog-local"}
        )
    )
    assert all(
        entry.access_model is not AccessModel.PAID
        for entry in manifest.entries
        if entry.production
    )
    assert all(
        entry.license_name
        and entry.attribution_text
        and entry.redistribution_policy
        and entry.cache_policy
        and entry.rate_limit_policy
        and entry.credential_class
        and entry.retention_limit_days > 0
        for entry in manifest.entries
    )


def test_rights_validation_rejects_paid_expired_and_future_production_entries() -> None:
    today = date(2026, 9, 14)

    def entry(*, access_model: AccessModel, reviewed: date) -> ProviderRights:
        return ProviderRights(
            asset_id=f"test-{access_model.value}-{reviewed.isoformat()}",
            authority="Test authority",
            license_name="Test license",
            attribution_text="Test attribution",
            redistribution_policy="Test redistribution",
            cache_policy="Test cache",
            rate_limit_policy="Test rate limits",
            credential_class="none",
            retention_limit_days=1,
            last_human_review=reviewed,
            access_model=access_model,
        )

    with pytest.raises(ValueError, match="Paid provider"):
        ProviderRightsManifest(
            "provider-rights.v1",
            "test",
            (entry(access_model=AccessModel.PAID, reviewed=today),),
        ).validate_production(today=today)
    with pytest.raises(ValueError, match="expired"):
        ProviderRightsManifest(
            "provider-rights.v1",
            "test",
            (
                entry(
                    access_model=AccessModel.PUBLIC,
                    reviewed=today - timedelta(days=366),
                ),
            ),
        ).validate_production(today=today)
    with pytest.raises(ValueError, match="future"):
        ProviderRightsManifest(
            "provider-rights.v1",
            "test",
            (
                entry(
                    access_model=AccessModel.PUBLIC,
                    reviewed=today + timedelta(days=1),
                ),
            ),
        ).validate_production(today=today)


def test_rights_manifest_rejects_unregistered_assets() -> None:
    manifest = load_provider_rights_manifest()
    with pytest.raises(ValueError, match="missing"):
        manifest.require_all(["not-registered"])
