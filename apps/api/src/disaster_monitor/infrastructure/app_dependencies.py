"""Typed runtime dependencies exposed to the FastAPI boundary."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from disaster_monitor.application.agent.diagnostics import AgentDiagnostics
from disaster_monitor.application.ports.conversation_store import ConversationStore
from disaster_monitor.application.ports.event_media import MediaAssetStore
from disaster_monitor.application.ports.geography import CountryCatalogUpdateAutomation
from disaster_monitor.application.ports.language_model import LanguageModel
from disaster_monitor.application.ports.operational_state import OperationalRepository
from disaster_monitor.application.ports.operator_identity import (
    TrustedOperatorIdentityPolicy,
)
from disaster_monitor.application.satellite_imagery import SatelliteImageryService
from disaster_monitor.application.services.active_incidents import (
    ActiveIncidentsService,
)
from disaster_monitor.application.services.provider_freshness import (
    ProviderFreshnessService,
)
from disaster_monitor.application.use_cases.delete_conversation import (
    DeleteConversation,
)
from disaster_monitor.application.use_cases.record_operator_action import (
    RecordOperatorAction,
)
from disaster_monitor.application.use_cases.run_conversation_turn import (
    RunConversationTurn,
)

AsyncHook = Callable[[], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class AppLifecycle:
    """Delegate ordered startup and shutdown owned by composition."""

    startup_hooks: tuple[AsyncHook, ...] = ()
    shutdown_hooks: tuple[AsyncHook, ...] = ()

    async def startup(self) -> None:
        try:
            for hook in self.startup_hooks:
                await hook()
        except BaseException:
            await self.shutdown()
            raise

    async def shutdown(self) -> None:
        for hook in self.shutdown_hooks:
            await hook()


@dataclass(frozen=True, slots=True)
class AppDependencies:
    """The single typed dependency object exposed through ``app.state``."""

    conversation_store: ConversationStore
    run_conversation_turn: RunConversationTurn
    delete_conversation: DeleteConversation
    language_model: LanguageModel
    active_incidents: ActiveIncidentsService
    satellite_imagery: SatelliteImageryService
    media_assets: MediaAssetStore
    operational_repository: OperationalRepository
    provider_freshness: ProviderFreshnessService
    record_operator_action: RecordOperatorAction
    operator_identity: TrustedOperatorIdentityPolicy
    country_catalog_automation: CountryCatalogUpdateAutomation
    agent_diagnostics: AgentDiagnostics | None
    lifecycle: AppLifecycle = field(default_factory=AppLifecycle)
