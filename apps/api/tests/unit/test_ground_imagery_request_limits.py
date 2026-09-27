from datetime import UTC, datetime, timedelta

import pytest

from disaster_monitor.application.ground_imagery.request_limits import (
    GroundImageryRateLimitExceeded,
    GroundImageryRequestLimiter,
)


@pytest.mark.asyncio
async def test_catalog_limits_distinct_searches_and_hourly_incident_refresh() -> None:
    now = datetime(2026, 9, 27, 12, tzinfo=UTC)
    limiter = GroundImageryRequestLimiter(clock=lambda: now)

    await limiter.claim_catalog_search("incident-1")
    with pytest.raises(GroundImageryRateLimitExceeded) as denied:
        await limiter.claim_catalog_search("incident-1")
    assert denied.value.retry_after_seconds == 3600

    for index in range(2, 7):
        await limiter.claim_catalog_search(f"incident-{index}")
    with pytest.raises(GroundImageryRateLimitExceeded):
        await limiter.claim_catalog_search("incident-7")

    now += timedelta(hours=1)
    await limiter.claim_catalog_search("incident-1")


@pytest.mark.asyncio
async def test_preparation_limits_four_per_hour_and_twelve_per_day() -> None:
    now = datetime(2026, 9, 27, 12, tzinfo=UTC)
    limiter = GroundImageryRequestLimiter(clock=lambda: now)

    for _hour in range(3):
        for _ in range(4):
            await limiter.claim_preparation()
        with pytest.raises(GroundImageryRateLimitExceeded):
            await limiter.claim_preparation()
        now += timedelta(hours=1)
    with pytest.raises(GroundImageryRateLimitExceeded):
        await limiter.claim_preparation()

    now += timedelta(days=1)
    await limiter.claim_preparation()


@pytest.mark.asyncio
async def test_catalog_limit_is_twenty_four_searches_per_day() -> None:
    now = datetime(2026, 9, 27, 0, tzinfo=UTC)
    limiter = GroundImageryRequestLimiter(clock=lambda: now)

    for hour in range(4):
        for index in range(6):
            await limiter.claim_catalog_search(f"incident-{hour}-{index}")
        now += timedelta(hours=1)
    with pytest.raises(GroundImageryRateLimitExceeded) as denied:
        await limiter.claim_catalog_search("incident-25")
    assert denied.value.retry_after_seconds == 20 * 3600
