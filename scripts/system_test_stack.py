"""Run the real Next.js UI against a fake-model FastAPI server."""

import asyncio
import os
import shutil
import subprocess
import tempfile
from dataclasses import replace
from pathlib import Path
from threading import Event, Thread

import uvicorn
from system_test_backend import (
    NOW,
    FakeSystemEventProvider,
    FakeSystemModel,
    FakeSystemSituationProvider,
    build_system_active_incidents_service,
)

from disaster_monitor.application.agent.operator_actions import OPERATOR_ACTION_IDS
from disaster_monitor.application.services.active_incidents import (
    ActiveIncidentsService,
)
from disaster_monitor.application.services.current_disaster_report import (
    CurrentDisasterReportService,
)
from disaster_monitor.application.services.operational_ingestion import (
    IncidentWatchScheduler,
    IncidentWatchWorker,
)
from disaster_monitor.application.services.provider_registry import (
    ProviderCapabilities,
    ProviderRole,
)
from disaster_monitor.application.use_cases.manage_incident_watches import (
    ManageIncidentWatches,
)
from disaster_monitor.application.use_cases.refresh_incident_watch import (
    RefreshIncidentWatch,
)
from disaster_monitor.domain.disaster import Disaster
from disaster_monitor.infrastructure.configuration import Settings
from disaster_monitor.infrastructure.disaster.composite import (
    CompositeDisasterEventProvider,
)
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
)
from disaster_monitor.infrastructure.llm.structured_agent_model import (
    StructuredAgentModel,
)
from disaster_monitor.infrastructure.operations.memory_repository import (
    InMemoryOperationalRepository,
)
from disaster_monitor.main import create_app

script_directory = Path(__file__).resolve().parent
web_directory = script_directory.parent / "apps" / "web"


def main() -> int:
    catalog_directory = tempfile.TemporaryDirectory(
        prefix="disaster-monitor-system-country-catalog-"
    )
    repository = InMemoryOperationalRepository()
    active_incidents = build_system_active_incidents_service()
    fake_model = FakeSystemModel()
    app = create_app(
        settings=Settings(
            allowed_origins="http://127.0.0.1:4173",
            country_catalog_automatic_updates=False,
            country_catalog_root=Path(catalog_directory.name),
        ),
        model=fake_model,
        agent_model=StructuredAgentModel(
            fake_model,
            operator_action_ids=tuple(sorted(OPERATOR_ACTION_IDS)),
        ),
        current_disaster_report=CurrentDisasterReportService(
            CompositeDisasterEventProvider((FakeSystemEventProvider(),)),
            FakeSystemSituationProvider(),
            provider_capabilities=(
                ProviderCapabilities(
                    frozenset({ProviderRole.EVENT_DISCOVERY}),
                    frozenset({Disaster.EARTHQUAKE, Disaster.FLOOD}),
                    None,
                ),
                ProviderCapabilities(
                    frozenset({ProviderRole.SITUATION_EVIDENCE}),
                    frozenset({Disaster.EARTHQUAKE, Disaster.FLOOD}),
                    None,
                ),
            ),
            clock=lambda: NOW,
        ),
        active_incidents_service=active_incidents,
        operational_repository=repository,
    )
    app.state.dependencies = replace(
        app.state.dependencies,
        incident_watches=ManageIncidentWatches(
            repository,
            StaticCountryCatalog(),
            clock=lambda: NOW,
        ),
    )
    api_server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=8787,
            log_level="warning",
        )
    )
    api_thread = Thread(target=api_server.run, daemon=True)
    api_thread.start()
    watch_runtime_stop = Event()
    watch_runtime_thread = Thread(
        target=_run_watch_runtime,
        args=(repository, active_incidents, watch_runtime_stop),
        daemon=True,
    )
    watch_runtime_thread.start()

    npm_command = "npm.cmd" if os.name == "nt" else "npm"
    web_environment = os.environ.copy()
    web_environment["NEXT_PUBLIC_API_BASE_URL"] = "http://127.0.0.1:8787/api/v1"
    subprocess.run(
        [npm_command, "run", "build"],
        cwd=web_directory,
        env=web_environment,
        check=True,
    )
    standalone_directory = _prepare_standalone_runtime(web_directory)
    web_environment["HOSTNAME"] = "127.0.0.1"
    web_environment["PORT"] = "4173"
    web_process = subprocess.Popen(
        ["node", "server.js"],
        cwd=standalone_directory,
        env=web_environment,
    )
    try:
        return web_process.wait()
    except KeyboardInterrupt:
        return 130
    finally:
        watch_runtime_stop.set()
        watch_runtime_thread.join(timeout=10)
        api_server.should_exit = True
        api_thread.join(timeout=10)
        if web_process.poll() is None:
            web_process.terminate()
            web_process.wait(timeout=10)
        catalog_directory.cleanup()


def _prepare_standalone_runtime(web_root: Path) -> Path:
    standalone_directory = web_root / ".next" / "standalone"
    shutil.copytree(
        web_root / ".next" / "static",
        standalone_directory / ".next" / "static",
        dirs_exist_ok=True,
    )
    public_directory = web_root / "public"
    if public_directory.is_dir():
        shutil.copytree(
            public_directory,
            standalone_directory / "public",
            dirs_exist_ok=True,
        )
    return standalone_directory


def _run_watch_runtime(
    repository: InMemoryOperationalRepository,
    active_incidents: ActiveIncidentsService,
    stop: Event,
) -> None:
    async def run() -> None:
        scheduler = IncidentWatchScheduler(repository)
        worker = IncidentWatchWorker(
            repository,
            RefreshIncidentWatch(repository, active_incidents),
            clock=lambda: NOW,
        )
        while not stop.is_set():
            await scheduler.enqueue_due(now=NOW)
            while await worker.run_once("system-incident-watch-worker") is not None:
                pass
            await asyncio.sleep(0.05)

    asyncio.run(run())


if __name__ == "__main__":
    raise SystemExit(main())
