from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from disaster_monitor.domain.web_collection import (
    WebFetchAudit,
    WebFetchOutcome,
    WebFetchState,
)
from disaster_monitor.infrastructure.operations.postgres_repository import (
    PostgresOperationalRepository,
)


@pytest.mark.asyncio
@pytest.mark.postgres
async def test_web_collection_state_and_audit_survive_repository_recreation(
    postgres_dsn: str,
) -> None:
    repository = PostgresOperationalRepository(postgres_dsn)
    await repository.migrate()
    now = datetime.now(UTC)
    identity = uuid4().hex
    source_id = f"approved-test-{identity}"
    state = WebFetchState(
        source_id,
        etag='"v1"',
        last_attempt_at=now,
        last_success_at=now,
        circuit_open_until=now + timedelta(minutes=30),
        consecutive_failures=3,
    )
    audit = WebFetchAudit(
        audit_id=f"web-fetch:{identity}",
        source_id=source_id,
        requested_url="https://news.example/disasters.xml",
        attempted_at=now,
        outcome=WebFetchOutcome.UPSTREAM_ERROR,
        status_code=503,
        bytes_received=0,
        response_sha256=None,
        error_code="upstream_http_error",
    )

    await repository.save_web_fetch_state(state)
    assert await repository.append_web_fetch_audit(audit)
    reopened = PostgresOperationalRepository(postgres_dsn)

    assert await reopened.read_web_fetch_state(source_id) == state
    assert await reopened.web_fetch_audits(source_id=source_id) == (audit,)
