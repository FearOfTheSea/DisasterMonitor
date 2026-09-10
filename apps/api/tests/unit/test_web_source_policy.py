from datetime import UTC, datetime, timedelta

import pytest

from disaster_monitor.domain.web_collection import (
    ApprovedWebSource,
    WebAcquisitionMode,
)

NOW = datetime(2026, 9, 10, 8, tzinfo=UTC)


def _source(**overrides: object) -> ApprovedWebSource:
    values = {
        "source_id": "approved-test-news",
        "publisher_name": "Test News",
        "feed_url": "https://news.example/disasters.xml",
        "allowed_hosts": ("news.example",),
        "allowed_path_prefixes": ("/disasters", "/articles/"),
        "acquisition_mode": WebAcquisitionMode.RSS_ATOM,
        "user_agent": "DisasterMonitor/1.0 (+mailto:ops@example.org)",
        "contact_email": "ops@example.org",
        "robots_policy_url": "https://news.example/robots.txt",
        "terms_url": "https://news.example/terms",
        "reviewed_at": NOW - timedelta(days=1),
        "review_expires_at": NOW + timedelta(days=30),
        "crawl_delay_seconds": 60,
        "request_limit_per_run": 1,
        "maximum_response_bytes": 100_000,
    }
    values.update(overrides)
    return ApprovedWebSource(**values)  # type: ignore[arg-type]


def test_approved_source_requires_https_allowlists_and_review_metadata() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        _source(feed_url="http://news.example/disasters.xml")
    with pytest.raises(ValueError, match="allowed host"):
        _source(feed_url="https://other.example/disasters.xml")
    with pytest.raises(ValueError, match="contact"):
        _source(contact_email="")


def test_source_admission_fails_closed_when_expired_disabled_or_killed() -> None:
    assert _source().is_admitted(NOW)
    assert not _source(review_expires_at=NOW).is_admitted(NOW)
    assert not _source(enabled=False).is_admitted(NOW)
    assert not _source(kill_switch_reason="publisher request").is_admitted(NOW)


def test_source_url_policy_rejects_paths_hosts_ports_and_credentials() -> None:
    source = _source()

    assert source.allows_url("https://news.example/articles/fire-1")
    assert not source.allows_url("https://news.example/politics/story")
    assert not source.allows_url("https://cdn.news.example/articles/fire-1")
    assert not source.allows_url("https://news.example:8443/articles/fire-1")
    assert not source.allows_url("https://user:secret@news.example/articles/fire-1")
    assert not source.allows_url("https://news.example/articles/%2e%2e/private/fire-1")
