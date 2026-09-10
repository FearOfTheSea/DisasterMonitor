"""Versioned loader for explicitly approved public-web sources."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import cast

from disaster_monitor.domain.web_collection import (
    ApprovedWebSource,
    WebAcquisitionMode,
)


class StaticApprovedWebSourceRegistry:
    def __init__(self, path: Path) -> None:
        if not path.is_file():
            raise ValueError("Approved web source registry does not exist.")
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            version = str(document["version"])
            source_documents = cast(list[dict[str, object]], document["sources"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ValueError("Approved web source registry is invalid.") from error
        if not version.strip():
            raise ValueError("Approved web source registry requires a version.")
        sources = tuple(_source(item) for item in source_documents)
        if len({source.source_id for source in sources}) != len(sources):
            raise ValueError("Approved web source registry contains duplicate IDs.")
        self._version = version
        self._sources = tuple(sorted(sources, key=lambda source: source.source_id))

    @property
    def version(self) -> str:
        return self._version

    def admitted(self, *, now: datetime) -> tuple[ApprovedWebSource, ...]:
        return tuple(source for source in self._sources if source.is_admitted(now))


def _source(item: dict[str, object]) -> ApprovedWebSource:
    try:
        return ApprovedWebSource(
            source_id=str(item["source_id"]),
            publisher_name=str(item["publisher_name"]),
            feed_url=str(item["feed_url"]),
            allowed_hosts=tuple(
                str(value) for value in cast(list[object], item["allowed_hosts"])
            ),
            allowed_path_prefixes=tuple(
                str(value)
                for value in cast(list[object], item["allowed_path_prefixes"])
            ),
            acquisition_mode=WebAcquisitionMode(str(item["acquisition_mode"])),
            user_agent=str(item["user_agent"]),
            contact_email=str(item["contact_email"]),
            robots_policy_url=str(item["robots_policy_url"]),
            terms_url=str(item["terms_url"]),
            reviewed_at=_datetime(item["reviewed_at"]),
            review_expires_at=_datetime(item["review_expires_at"]),
            crawl_delay_seconds=int(str(item["crawl_delay_seconds"])),
            request_limit_per_run=int(str(item["request_limit_per_run"])),
            maximum_response_bytes=int(str(item["maximum_response_bytes"])),
            enabled=_boolean(item.get("enabled", False)),
            kill_switch_reason=(
                str(item["kill_switch_reason"])
                if item.get("kill_switch_reason") is not None
                else None
            ),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("Approved web source entry is invalid.") from error


def _datetime(value: object) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Approved source review timestamps require a timezone.")
    return parsed


def _boolean(value: object) -> bool:
    if not isinstance(value, bool):
        raise ValueError("Approved source admission flags must be booleans.")
    return value
