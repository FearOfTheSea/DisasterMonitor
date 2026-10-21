"""Storage encoding preserves source accounts and rejects corrupt compressed views."""

from datetime import UTC, datetime

import pytest
from pydantic import TypeAdapter

from disaster_monitor.application.ports.discovery import DiscoveryCapacityError
from disaster_monitor.domain.discovery import (
    DiscoveryArticle,
    DiscoveryRun,
    ReportingInterval,
    assess_article,
    group_reports,
)
from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.infrastructure.operations.collection_run_payloads import (
    DiscoveryRunPayloads,
)

NOW = datetime(2026, 10, 20, tzinfo=UTC)


@pytest.fixture
def large_run():
    source = SourceReference(
        "news",
        "Daily",
        "Floods in Riverton",
        "https://news.example/flood",
        NOW,
        None,
        NOW,
        snapshot_id="retained-snapshot",
    )
    interval = ReportingInterval.at_start(30, NOW)
    report = assess_article(
        DiscoveryArticle(
            source,
            "Floods struck Riverton on 14 October 2026. Two people died. "
            + "Original source wording, dates, scope and attribution remain. " * 2_000,
        ),
        interval,
    )
    return DiscoveryRun(
        "preserved", interval, reports=(report,), events=group_reports((report,))
    )


def test_compressed_projection_preserves_all_source_accounts_and_identity(large_run):
    codec = DiscoveryRunPayloads()
    payload = codec.encode(large_run)
    assert len(payload) < len(TypeAdapter(DiscoveryRun).dump_json(large_run)) // 2
    assert codec.decode(payload) == large_run


def test_small_plain_json_and_existing_large_json_are_supported(large_run):
    codec = DiscoveryRunPayloads()
    small = DiscoveryRun("small", ReportingInterval.at_start(1, NOW))
    assert codec.decode(codec.encode(small)) == small
    raw = TypeAdapter(DiscoveryRun).dump_json(large_run)
    assert codec.decode(raw) == large_run
    assert codec.decode(raw.decode("utf-8")) == large_run


@pytest.mark.parametrize("damage", ["truncate", "trailing", "corrupt"])
def test_corrupt_compressed_projection_is_not_accepted_as_empty(large_run, damage):
    codec = DiscoveryRunPayloads()
    payload = codec.encode(large_run)
    if damage == "truncate":
        payload = payload[:-4]
    elif damage == "trailing":
        payload += b"unexpected trailing bytes"
    else:
        payload = payload[:20] + b"invalid" + payload[27:]
    with pytest.raises(ValueError):
        codec.decode(payload)


def test_unsupported_projection_encoding_fails_explicitly():
    with pytest.raises(ValueError, match="Unsupported"):
        DiscoveryRunPayloads().decode(b"DMRUN-ZLIB-999:unrecognized")


def test_compressed_expansion_is_bounded(large_run):
    payload = DiscoveryRunPayloads().encode(large_run)
    with pytest.raises(ValueError, match="decode limit"):
        DiscoveryRunPayloads(maximum_bytes=1024).decode(payload)


def test_new_oversized_projection_is_a_capacity_failure(large_run):
    with pytest.raises(DiscoveryCapacityError):
        DiscoveryRunPayloads(maximum_bytes=1024).encode(large_run)


def test_lower_new_write_limit_does_not_hide_existing_plain_json(large_run):
    raw = TypeAdapter(DiscoveryRun).dump_json(large_run)
    assert DiscoveryRunPayloads(maximum_bytes=1024).decode(raw) == large_run


def test_projection_limit_must_be_positive():
    with pytest.raises(ValueError, match="positive"):
        DiscoveryRunPayloads(maximum_bytes=0)
