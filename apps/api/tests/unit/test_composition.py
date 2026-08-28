from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest
from conftest import FakeLanguageModel

from disaster_monitor.application.agent.diagnostics import (
    AgentCapability,
    AgentCapabilityDiagnostic,
    AgentCapabilityFailure,
    AgentDiagnostics,
)
from disaster_monitor.infrastructure.app_dependencies import AppLifecycle
from disaster_monitor.infrastructure.composition import (
    AppDependencyOverrides,
    build_app_dependencies,
)
from disaster_monitor.infrastructure.configuration import Settings
from disaster_monitor.infrastructure.conversations.memory_repository import (
    InMemoryConversationRepository,
)
from disaster_monitor.infrastructure.llm.structured_agent_model import (
    StructuredAgentModel,
)
from disaster_monitor.infrastructure.memory.postgres_repository import (
    PostgresMemoryRepository,
)
from disaster_monitor.infrastructure.operations.memory_repository import (
    InMemoryOperationalRepository,
)
from disaster_monitor.main import create_app
from disaster_monitor.presentation.http.metrics import OperationalMetrics
from disaster_monitor.presentation.http.routes import get_operational_metrics


class RecordingDeletionStore:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    async def delete(self, conversation_id: str) -> bool:
        self.deleted.append(conversation_id)
        return True


class ClosableLanguageModel(FakeLanguageModel):
    close_count = 0

    async def aclose(self) -> None:
        self.close_count += 1


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        country_catalog_root=tmp_path / "geography",
        country_catalog_automatic_updates=False,
        event_media_enabled=False,
        operational_blob_root=tmp_path / "operational",
    )


def test_typed_overrides_construct_the_requested_dependencies(tmp_path: Path) -> None:
    model = FakeLanguageModel()
    repository = InMemoryOperationalRepository()
    overrides = AppDependencyOverrides(
        model=model,
        operational_repository=repository,
    )

    dependencies = build_app_dependencies(_settings(tmp_path), overrides=overrides)

    assert dependencies.language_model is model
    assert dependencies.operational_repository is repository


def test_mixed_persistence_requires_an_explicit_deletion_store(
    tmp_path: Path,
) -> None:
    overrides = AppDependencyOverrides(
        model=FakeLanguageModel(),
        conversation_repository=InMemoryConversationRepository(),
        memory_repository=PostgresMemoryRepository(
            "postgresql://test@database/disastermonitor"
        ),
    )

    with pytest.raises(ValueError, match="atomic conversation deletion"):
        build_app_dependencies(_settings(tmp_path), overrides=overrides)


@pytest.mark.asyncio
async def test_explicit_deletion_store_supports_mixed_persistence(
    tmp_path: Path,
) -> None:
    deletion_store = RecordingDeletionStore()
    dependencies = build_app_dependencies(
        _settings(tmp_path),
        overrides=AppDependencyOverrides(
            model=FakeLanguageModel(),
            conversation_repository=InMemoryConversationRepository(),
            memory_repository=PostgresMemoryRepository(
                "postgresql://test@database/disastermonitor"
            ),
            conversation_deletion_store=deletion_store,
        ),
    )

    await dependencies.delete_conversation.execute("conversation-a")

    assert deletion_store.deleted == ["conversation-a"]


def test_create_app_accepts_prebuilt_dependencies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    dependencies = build_app_dependencies(
        settings,
        overrides=AppDependencyOverrides(model=FakeLanguageModel()),
    )

    def unexpected_build(*args: object, **kwargs: object) -> object:
        raise AssertionError("prebuilt dependencies must bypass production composition")

    monkeypatch.setattr(
        "disaster_monitor.main.build_app_dependencies", unexpected_build
    )

    app = create_app(settings=settings, dependencies=dependencies)

    assert app.state.dependencies is dependencies


def test_prebuilt_dependencies_reuse_application_diagnostics_metrics(
    tmp_path: Path,
) -> None:
    metrics = OperationalMetrics()
    settings = _settings(tmp_path)
    dependencies = build_app_dependencies(
        settings,
        overrides=AppDependencyOverrides(
            model=FakeLanguageModel(),
            agent_diagnostics=metrics,
        ),
    )

    app = create_app(settings=settings, dependencies=dependencies)

    assert dependencies.agent_diagnostics is metrics
    assert app.dependency_overrides[get_operational_metrics]() is metrics


@pytest.mark.asyncio
async def test_lifecycle_hooks_keep_declared_startup_and_shutdown_order() -> None:
    events: list[str] = []

    def hook(name: str) -> Callable[[], Awaitable[None]]:
        async def run() -> None:
            events.append(name)

        return run

    lifecycle = AppLifecycle(
        startup_hooks=(hook("start-a"), hook("start-b")),
        shutdown_hooks=(hook("stop-a"), hook("stop-b")),
    )

    await lifecycle.startup()
    await lifecycle.shutdown()

    assert events == ["start-a", "start-b", "stop-a", "stop-b"]


@pytest.mark.asyncio
async def test_failed_startup_runs_shutdown_hooks_for_constructed_resources() -> None:
    events: list[str] = []

    async def started() -> None:
        events.append("started")

    async def failed() -> None:
        events.append("failed")
        raise RuntimeError("startup failed")

    async def closed() -> None:
        events.append("closed")

    lifecycle = AppLifecycle(
        startup_hooks=(started, failed),
        shutdown_hooks=(closed,),
    )

    with pytest.raises(RuntimeError, match="startup failed"):
        await lifecycle.startup()

    assert events == ["started", "failed", "closed"]


@pytest.mark.asyncio
async def test_shared_language_model_is_closed_exactly_once(tmp_path: Path) -> None:
    model = ClosableLanguageModel()
    dependencies = build_app_dependencies(
        _settings(tmp_path),
        overrides=AppDependencyOverrides(
            model=model,
            agent_model=StructuredAgentModel(model),
        ),
    )

    await dependencies.lifecycle.shutdown()

    assert model.close_count == 1


def test_agent_metrics_implement_the_application_diagnostics_contract() -> None:
    metrics = OperationalMetrics()
    diagnostics: AgentDiagnostics = metrics

    diagnostics.record(
        AgentCapabilityDiagnostic(
            AgentCapability.EVENT_MEDIA_DISCOVERY,
            AgentCapabilityFailure.DEPENDENCY_FAILURE,
            attempt_count=1,
        )
    )

    content, _ = metrics.render()
    assert b"disastermonitor_agent_optional_capability_failures_total" in content
    assert b'capability="event_media_discovery"' in content
