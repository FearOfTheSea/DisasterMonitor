"""Standalone HTTP contracts have no assistant dependency."""

from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
from fastapi import FastAPI

from disaster_monitor.application.evidence.standalone_models import (
    StandaloneEvidenceResult,
)
from disaster_monitor.application.media import (
    DisasterMediaGallery,
    MediaContinuationError,
)
from disaster_monitor.presentation.http.standalone_evidence_routes import router


async def test_media_continuation_query_preserves_cursor_and_public_failure_states():
    calls = []
    token = "opaque-page+/="

    class Evidence:
        async def execute(self, identifier, section, *, cursor=None):
            calls.append((identifier, section, cursor))
            if cursor is not None and section != "media":
                raise ValueError("Continuation is supported only for photographs.")
            if cursor == "changed":
                raise MediaContinuationError("Source changed. Restart photographs.")
            now = datetime.now(UTC)
            return StandaloneEvidenceResult(
                identifier,
                "physical:test",
                "media",
                "empty",
                now,
                media=DisasterMediaGallery(
                    identifier,
                    "physical:test",
                    now,
                    (),
                    0,
                    (),
                    next_cursor=token if cursor is None else None,
                ),
            )

    app = FastAPI()
    app.state.dependencies = SimpleNamespace(standalone_evidence=Evidence())
    app.include_router(router, prefix="/api/v1")
    path = "/api/v1/incidents/discovery%3Asnapshot/evidence/media"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = await client.get(path)
        assert first.status_code == 200
        assert first.json()["evidence"]["media"]["next_cursor"] == token
        next_page = await client.get(path, params={"cursor": token})
        assert next_page.status_code == 200
        assert next_page.json()["evidence"]["media"]["next_cursor"] is None
        assert calls[-1] == ("discovery:snapshot", "media", token)
        changed = await client.get(path, params={"cursor": "changed"})
        assert changed.status_code == 400 and "Restart" in changed.json()["detail"]
        assert (
            await client.get(path, params={"cursor": "x" * 8193})
        ).status_code == 422
        assert (await client.get(path, params={"cursor": ""})).status_code == 422
        assert (
            await client.get(
                path.replace("/media", "/exposure"), params={"cursor": token}
            )
        ).status_code == 400


async def test_section_http_states_and_bounded_inspection():
    class Evidence:
        async def execute(self, identifier, section, *, cursor=None):
            if identifier == "missing":
                raise LookupError("Incident unavailable")
            if identifier == "ambiguous":
                raise ValueError("Incident identifier is ambiguous")
            if section != "exposure":
                raise ValueError("Unsupported evidence section")
            return StandaloneEvidenceResult(
                identifier, "physical:test", section, "unconfigured", datetime.now(UTC)
            )

        async def execute_inspection(self, identifier, bounds):
            if bounds == (-180, -90, 180, 90):
                raise ValueError("Area exceeds bounded inspection limit")
            return await self.execute(identifier, "exposure")

    app = FastAPI()
    app.state.dependencies = SimpleNamespace(standalone_evidence=Evidence())
    app.include_router(router, prefix="/api/v1")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        result = await client.get("/api/v1/incidents/provider%3A1/evidence/exposure")
        assert result.status_code == 200
        assert result.json()["evidence"]["state"] == "unconfigured"
        for identifier, section, expected in (
            ("missing", "exposure", 404),
            ("ambiguous", "exposure", 409),
            ("selected", "assistant", 400),
        ):
            assert (
                await client.get(f"/api/v1/incidents/{identifier}/evidence/{section}")
            ).status_code == expected
        oversized = await client.post(
            "/api/v1/incidents/selected/evidence/exposure/inspection",
            json={"bounds": [-180, -90, 180, 90]},
        )
        assert oversized.status_code == 422
        app.state.dependencies = SimpleNamespace(standalone_evidence=None)
        unavailable = await client.get("/api/v1/incidents/selected/evidence/exposure")
        assert unavailable.status_code == 503
