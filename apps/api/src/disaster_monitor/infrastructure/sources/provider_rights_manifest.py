"""Load and validate the packaged provider-rights manifest."""

from __future__ import annotations

import json
from datetime import date
from importlib.resources import files
from typing import cast

from disaster_monitor.application.ports.provider_rights import (
    AccessModel,
    ProviderRights,
    ProviderRightsManifest,
)


def load_provider_rights_manifest() -> ProviderRightsManifest:
    resource = files("disaster_monitor.infrastructure.sources.resources").joinpath(
        "provider_rights.v1.json"
    )
    document = cast(dict[str, object], json.loads(resource.read_text(encoding="utf-8")))
    entries = tuple(
        ProviderRights(
            asset_id=str(item["asset_id"]),
            authority=str(item["authority"]),
            license_name=str(item["license"]),
            attribution_text=str(item["attribution"]),
            redistribution_policy=str(item["redistribution"]),
            cache_policy=str(item["cache_policy"]),
            rate_limit_policy=str(item["rate_limits"]),
            credential_class=str(item["credential_class"]),
            retention_limit_days=int(cast(int | str, item["retention_limit_days"])),
            last_human_review=date.fromisoformat(str(item["last_human_review"])),
            access_model=AccessModel(str(item["access_model"])),
            production=bool(item.get("production", True)),
        )
        for item in cast(list[dict[str, object]], document["entries"])
    )
    manifest = ProviderRightsManifest(
        schema_version=str(document["schema_version"]),
        version=str(document["version"]),
        entries=entries,
    )
    manifest.validate_production(today=date.today())
    return manifest
