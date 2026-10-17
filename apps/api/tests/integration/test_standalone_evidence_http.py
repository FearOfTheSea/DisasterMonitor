"""Standalone HTTP contracts have no assistant dependency."""

from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
from fastapi import FastAPI

from disaster_monitor.application.evidence.standalone_models import (
    StandaloneEvidenceResult,
)
from disaster_monitor.presentation.http.standalone_evidence_routes import router


async def test_section_http_states_and_bounded_inspection():
    class Evidence:
        async def execute(self, identifier, section):
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
