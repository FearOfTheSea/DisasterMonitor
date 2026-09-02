"""Serialization from application/domain results to HTTP response models."""

from disaster_monitor.application.ports.geography import CountryCatalogUpdateStatus
from disaster_monitor.presentation.http.schemas import (
    CountryCatalogSourceResponse,
    CountryCatalogUpdateResponse,
)


def _country_catalog_response(
    value: CountryCatalogUpdateStatus,
) -> CountryCatalogUpdateResponse:
    return CountryCatalogUpdateResponse(
        state=value.state.value,
        active_version=value.active_version,
        country_count=value.country_count,
        automatic_updates_enabled=value.automatic_updates_enabled,
        trigger=value.trigger.value if value.trigger else None,
        last_attempt_at=value.last_attempt_at,
        last_success_at=value.last_success_at,
        next_scheduled_at=value.next_scheduled_at,
        message=value.message,
        failure_code=value.failure_code,
        sources=[
            CountryCatalogSourceResponse(
                source_id=source.source_id,
                version=source.version,
                revision=source.revision,
                sha256=source.sha256,
            )
            for source in value.sources
        ],
    )
