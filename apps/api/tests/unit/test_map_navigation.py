from disaster_monitor.application.dto import ModelToolCall
from disaster_monitor.application.services.map_navigation import (
    FIT_COUNTRY_TOOL,
    MapNavigationService,
)
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
)


def test_country_tool_is_catalog_backed_and_executes_to_validated_bounds() -> None:
    service = MapNavigationService(StaticCountryCatalog())

    tool = service.model_tools()[0]
    action = service.execute_model_calls(
        (ModelToolCall(FIT_COUNTRY_TOOL, {"country_code": "JPN"}),),
        admitted_text="Zoom into Japan.",
    )

    assert tool.name == FIT_COUNTRY_TOOL
    assert tool.parameters["properties"] == {
        "country_code": {
            "type": "string",
            "enum": ["JPN", "VNM", "VEN"],
            "description": (
                "Supported country mappings: JPN = Japan; VNM = Vietnam; "
                "VEN = Venezuela."
            ),
        }
    }
    assert action is not None
    assert action.label == "Japan"
    assert action.bounds == (122.0, 20.0, 154.0, 46.0)


def test_country_tool_fails_closed_for_unallowlisted_or_ambiguous_calls() -> None:
    service = MapNavigationService(StaticCountryCatalog())

    assert (
        service.execute_model_calls(
            (ModelToolCall(FIT_COUNTRY_TOOL, {"country_code": "USA"}),),
            admitted_text="Zoom into Japan.",
        )
        is None
    )
    assert (
        service.execute_model_calls(
            (
                ModelToolCall(FIT_COUNTRY_TOOL, {"country_code": "JPN"}),
                ModelToolCall(FIT_COUNTRY_TOOL, {"country_code": "VNM"}),
            ),
            admitted_text="Show Japan and Vietnam.",
        )
        is None
    )
    assert (
        service.execute_model_calls(
            (
                ModelToolCall(
                    FIT_COUNTRY_TOOL,
                    {"country_code": "JPN", "zoom": 18},
                ),
            ),
            admitted_text="Zoom into Japan.",
        )
        is None
    )
    assert (
        service.execute_model_calls(
            (ModelToolCall(FIT_COUNTRY_TOOL, {"country_code": "VNM"}),),
            admitted_text="Zoom into Japan.",
        )
        is None
    )
