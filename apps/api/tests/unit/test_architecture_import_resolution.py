from .architecture_support import imported_modules


def test_relative_imports_resolve_outward_layer_access() -> None:
    imports = imported_modules(
        "from ...infrastructure import configuration\n"
        "from ... import infrastructure\n"
        "from .models import Event\n"
        "import httpx as client",
        module="disaster_monitor.application.incidents.query",
    )
    assert imports == (
        "disaster_monitor.infrastructure",
        "disaster_monitor.infrastructure",
        "disaster_monitor.application.incidents.models",
        "httpx",
    )


def test_package_relative_imports_resolve_from_the_package_itself() -> None:
    assert imported_modules(
        "from . import child", module="disaster_monitor.domain", is_package=True
    ) == ("disaster_monitor.domain.child",)
