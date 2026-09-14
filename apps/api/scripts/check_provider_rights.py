"""Fail-closed validation for every production provider and imagery layer."""

from __future__ import annotations

import json
from datetime import date

from disaster_monitor.infrastructure.satellite_imagery.providers import (
    NasaGibsImageryProvider,
)
from disaster_monitor.infrastructure.sources.provider_rights_manifest import (
    load_provider_rights_manifest,
)
from disaster_monitor.infrastructure.sources.static_source_catalog import (
    StaticSourceCatalog,
)


def main() -> int:
    manifest = load_provider_rights_manifest()
    source_ids = tuple(item.source_id for item in StaticSourceCatalog().sources())
    imagery_ids = tuple(
        product.rights_id for product in NasaGibsImageryProvider().products
    )
    required_ids = (
        source_ids
        + imagery_ids
        + (
            "nasa-gibs",
            "copernicus-data-space-ground",
            "open-cog-local",
        )
    )
    manifest.require_all(required_ids)
    manifest.validate_production(today=date.today())
    production = [
        entry
        for entry in manifest.entries
        if entry.asset_id in set(required_ids) and entry.production
    ]
    if any(entry.access_model.value == "paid" for entry in production):
        raise ValueError("A production provider is marked with paid access.")
    print(
        json.dumps(
            {
                "manifest_version": manifest.version,
                "required_assets": len(set(required_ids)),
                "production_assets": len(production),
                "access_models": sorted(
                    {entry.access_model.value for entry in production}
                ),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
