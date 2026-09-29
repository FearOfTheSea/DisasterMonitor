"""A named Indonesian eruption must remain eligible for trusted retrieval."""

from disaster_monitor.application.agent.models import TaskKind, ValidationStatus
from disaster_monitor.application.agent.task_normalization import (
    deterministic_task_draft,
    validate_disaster_task,
)
from disaster_monitor.application.investigation.disaster_query_parser import (
    DisasterQueryParser,
)
from disaster_monitor.domain.disaster import Disaster
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
)


def test_september_krakatau_request_resolves_indonesia_and_place() -> None:
    catalog = StaticCountryCatalog()
    question = (
        "What happened during the September 4, 2026 Krakatau eruption in Indonesia?"
    )

    task = validate_disaster_task(
        question,
        deterministic_task_draft(question),
        country_catalog=catalog,
        query_parser=DisasterQueryParser(catalog),
    )

    assert task.kind is TaskKind.INVESTIGATION
    assert task.validation_status is ValidationStatus.VALID
    assert task.disaster is Disaster.VOLCANIC_ERUPTION
    assert task.country is not None and task.country.alpha3_code == "IDN"
    assert task.query is not None and task.query.location_hint == "Krakatau"
