"""US state wording must resolve through maintained geography without losing place."""

from disaster_monitor.application.agent.models import (
    DisasterTaskDraft,
    TaskKind,
    ValidationStatus,
)
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


def test_nikolski_alaska_resolves_usa_and_keeps_nikolski_place() -> None:
    catalog = StaticCountryCatalog()
    question = "What happened in the September 3 earthquake near Nikolski, Alaska?"
    draft = DisasterTaskDraft(
        disaster_related=True,
        current_or_event_specific=True,
        task_kind=TaskKind.INVESTIGATION,
        disaster=Disaster.EARTHQUAKE,
        country_name="Alaska",
        canonical=True,
    )

    task = validate_disaster_task(
        question,
        draft,
        country_catalog=catalog,
        query_parser=DisasterQueryParser(catalog),
    )

    assert task.validation_status is ValidationStatus.VALID
    assert task.country is not None and task.country.alpha3_code == "USA"
    assert task.query is not None and task.query.location_hint == "Nikolski"


def test_alaska_resolves_on_deterministic_fallback() -> None:
    catalog = StaticCountryCatalog()
    question = "Latest earthquake near Nikolski, Alaska?"
    task = validate_disaster_task(
        question,
        deterministic_task_draft(question),
        country_catalog=catalog,
        query_parser=DisasterQueryParser(catalog),
    )

    assert task.validation_status is ValidationStatus.VALID
    assert task.country is not None and task.country.alpha3_code == "USA"


def test_ambiguous_georgia_requires_country_clarification() -> None:
    catalog = StaticCountryCatalog()
    question = "Latest earthquake in Georgia?"
    task = validate_disaster_task(
        question,
        deterministic_task_draft(question),
        country_catalog=catalog,
        query_parser=DisasterQueryParser(catalog),
    )

    assert task.validation_status is ValidationStatus.CLARIFICATION_REQUIRED
    assert task.country is None

    canonical = validate_disaster_task(
        question,
        DisasterTaskDraft(
            disaster_related=True,
            current_or_event_specific=True,
            task_kind=TaskKind.INVESTIGATION,
            disaster=Disaster.EARTHQUAKE,
            country_name="Georgia",
            canonical=True,
        ),
        country_catalog=catalog,
        query_parser=DisasterQueryParser(catalog),
    )
    assert canonical.validation_status is ValidationStatus.CLARIFICATION_REQUIRED
    assert canonical.country is None
