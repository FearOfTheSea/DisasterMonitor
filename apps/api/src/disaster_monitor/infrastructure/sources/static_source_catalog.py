"""Static versioned source-intelligence catalog adapter."""

import json
from importlib.resources import files
from typing import cast

from disaster_monitor.application.agent.models import (
    SourceDescriptor,
    SourceInformationRole,
)
from disaster_monitor.domain.disaster import Hazard


class StaticSourceCatalog:
    def __init__(self) -> None:
        resource = files("disaster_monitor.infrastructure.sources.resources").joinpath(
            "disaster_sources.v1.json"
        )
        payload = json.loads(resource.read_text(encoding="utf-8"))
        self._version = str(payload["version"])
        self._sources = tuple(_descriptor(item) for item in payload["sources"])
        if len({item.source_id for item in self._sources}) != len(self._sources):
            raise ValueError("The packaged source catalog has duplicate source IDs.")
        self._by_id = {item.source_id: item for item in self._sources}

    @property
    def version(self) -> str:
        return self._version

    def sources(self) -> tuple[SourceDescriptor, ...]:
        return self._sources

    def get(self, source_id: str) -> SourceDescriptor | None:
        return self._by_id.get(source_id)


def _descriptor(item: dict[str, object]) -> SourceDescriptor:
    country_codes = item["country_codes"]
    roles = cast(list[str], item["information_roles"])
    hazards = cast(list[str], item["supported_hazards"])
    languages = cast(list[str], item["supported_languages"])
    limitations = cast(list[str], item["limitations"])
    tool_names = cast(list[str], item["registered_tool_names"])
    return SourceDescriptor(
        source_id=str(item["source_id"]),
        organization_name=str(item["organization_name"]),
        display_name=str(item["display_name"]),
        jurisdiction=str(item["jurisdiction"]),
        authority_level=str(item["authority_level"]),
        information_roles=tuple(SourceInformationRole(value) for value in roles),
        supported_hazards=tuple(Hazard(value) for value in hazards),
        country_codes=(
            None
            if country_codes is None
            else tuple(str(value) for value in cast(list[str], country_codes))
        ),
        supported_languages=tuple(languages),
        endpoint_kind=str(item["endpoint_kind"]),
        requires_configuration=bool(item["requires_configuration"]),
        configured=bool(item["configured"]),
        expected_freshness=str(item["expected_freshness"]),
        attribution_guidance=str(item["attribution_guidance"]),
        limitations=tuple(limitations),
        registered_tool_names=tuple(tool_names),
        provider_registration_name=str(item["provider_registration_name"]),
        implementation_status=str(item["implementation_status"]),
    )
