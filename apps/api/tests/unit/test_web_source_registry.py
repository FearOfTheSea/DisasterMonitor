import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from disaster_monitor.infrastructure.composition_builders import (
    build_breaking_news_feeds,
)
from disaster_monitor.infrastructure.configuration import Settings
from disaster_monitor.infrastructure.news.web_source_registry import (
    StaticApprovedWebSourceRegistry,
)
from disaster_monitor.infrastructure.operations.memory_repository import (
    InMemoryOperationalRepository,
)

NOW = datetime(2026, 9, 10, 8, tzinfo=UTC)


def _document(source_id: str = "approved-test-news") -> dict[str, object]:
    return {
        "source_id": source_id,
        "publisher_name": "Test News",
        "feed_url": "https://news.example/disasters.xml",
        "allowed_hosts": ["news.example"],
        "allowed_path_prefixes": ["/disasters", "/articles/"],
        "acquisition_mode": "rss_atom",
        "user_agent": "DisasterMonitor/1.0 (+mailto:ops@example.org)",
        "contact_email": "ops@example.org",
        "robots_policy_url": "https://news.example/robots.txt",
        "terms_url": "https://news.example/terms",
        "reviewed_at": (NOW - timedelta(days=1)).isoformat(),
        "review_expires_at": (NOW + timedelta(days=30)).isoformat(),
        "crawl_delay_seconds": 60,
        "request_limit_per_run": 1,
        "maximum_response_bytes": 100000,
        "enabled": True,
    }


def _write(path: Path, sources: list[dict[str, object]]) -> None:
    path.write_text(json.dumps({"version": "1.0.0", "sources": sources}))


def test_registry_loads_only_currently_admitted_sources(tmp_path: Path) -> None:
    path = tmp_path / "sources.json"
    expired = _document("expired-test-news")
    expired["review_expires_at"] = NOW.isoformat()
    _write(path, [_document(), expired])

    registry = StaticApprovedWebSourceRegistry(path)

    assert registry.version == "1.0.0"
    assert [source.source_id for source in registry.admitted(now=NOW)] == [
        "approved-test-news"
    ]


def test_registry_rejects_duplicate_source_ids(tmp_path: Path) -> None:
    path = tmp_path / "sources.json"
    _write(path, [_document(), _document()])

    with pytest.raises(ValueError, match="duplicate"):
        StaticApprovedWebSourceRegistry(path)


def test_registry_rejects_non_boolean_admission_flags(tmp_path: Path) -> None:
    path = tmp_path / "sources.json"
    source = _document()
    source["enabled"] = "false"
    _write(path, [source])

    with pytest.raises(ValueError, match="entry is invalid"):
        StaticApprovedWebSourceRegistry(path)


def test_composition_adds_only_admitted_controlled_sources(tmp_path: Path) -> None:
    path = tmp_path / "sources.json"
    _write(path, [_document()])

    feeds = build_breaking_news_feeds(
        Settings(
            _env_file=None,
            gdelt_news_enabled=False,
            approved_web_source_registry_path=path,
        ),
        InMemoryOperationalRepository(),
        now=NOW,
    )

    assert [feed.source_id for feed in feeds] == ["approved-test-news"]
