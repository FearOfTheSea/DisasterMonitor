import ast
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "disaster_monitor"
DOMAIN = SRC / "domain"
APPLICATION = SRC / "application"
INFRASTRUCTURE = SRC / "infrastructure"
PRESENTATION = SRC / "presentation"
INCIDENT_PRIORITY = APPLICATION / "services" / "incident_priority.py"
CONVERSATION_STORE = APPLICATION / "ports" / "conversation_store.py"
MEMORY_STORE = APPLICATION / "ports" / "memory_store.py"
MAIN = SRC / "main.py"

INFRASTRUCTURE_COMPOSITION_MODULES = {
    "disaster_monitor.infrastructure.app_dependencies",
    "disaster_monitor.infrastructure.composition",
    "disaster_monitor.infrastructure.operations.runtime",
}
INFRASTRUCTURE_COMPOSITION_PREFIXES = (
    "disaster_monitor.infrastructure.disaster.registrations.",
)
INFRASTRUCTURE_APPLICATION_SURFACE = {
    "disaster_monitor.application.agent.models",
    "disaster_monitor.application.disaster",
    "disaster_monitor.application.dto",
    "disaster_monitor.application.media",
    "disaster_monitor.application.multimodal",
    "disaster_monitor.application.ports",
    "disaster_monitor.application.prompts.visual_analysis",
    "disaster_monitor.application.satellite_imagery",
    "disaster_monitor.application.source_intelligence",
}

DISASTER_POLICY_MODULES = {
    "disaster_monitor.application.disaster_aliases",
    "disaster_monitor.application.services.disaster_query_policy",
    "disaster_monitor.application.services.event_media",
    "disaster_monitor.application.services.evidence_correlation",
    "disaster_monitor.application.services.incident_priority_policy",
    "disaster_monitor.application.services.report_profiles",
    "disaster_monitor.application.services.worldwide_disaster_policy",
}


def _python_files(directory: Path) -> tuple[Path, ...]:
    return tuple(
        path for path in directory.rglob("*.py") if "__pycache__" not in path.parts
    )


def _imports(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return tuple(imports)


def _module_name(path: Path) -> str:
    relative = path.relative_to(SRC.parent).with_suffix("")
    return ".".join(relative.parts)


def test_domain_imports_only_standard_library() -> None:
    standard_library = sys.stdlib_module_names | {"__future__"}
    violations = [
        f"{path.relative_to(SRC)} imports {name}"
        for path in _python_files(DOMAIN)
        for name in _imports(path)
        if name.split(".", 1)[0] not in standard_library
    ]

    assert violations == []


def test_application_does_not_import_outward_dependencies() -> None:
    forbidden_roots = {
        "fastapi",
        "httpx",
        "next",
        "ollama",
        "pydantic",
        "pypdf",
        "react",
    }
    violations = []
    for path in _python_files(APPLICATION):
        for name in _imports(path):
            root = name.split(".", 1)[0]
            if root in forbidden_roots or name.startswith(
                (
                    "disaster_monitor.infrastructure",
                    "disaster_monitor.presentation",
                )
            ):
                violations.append(f"{path.relative_to(SRC)} imports {name}")

    assert violations == []


def test_presentation_does_not_import_infrastructure() -> None:
    violations = [
        f"{path.relative_to(SRC)} imports {name}"
        for path in _python_files(PRESENTATION)
        for name in _imports(path)
        if name == "disaster_monitor.infrastructure"
        or name.startswith("disaster_monitor.infrastructure.")
    ]

    assert violations == []


def test_infrastructure_does_not_import_presentation() -> None:
    violations = [
        f"{path.relative_to(SRC)} imports {name}"
        for path in _python_files(INFRASTRUCTURE)
        for name in _imports(path)
        if name == "disaster_monitor.presentation"
        or name.startswith("disaster_monitor.presentation.")
    ]

    assert violations == []


def test_infrastructure_imports_only_application_contract_surface() -> None:
    violations = []
    for path in _python_files(INFRASTRUCTURE):
        module = _module_name(path)
        if module in INFRASTRUCTURE_COMPOSITION_MODULES or module.startswith(
            INFRASTRUCTURE_COMPOSITION_PREFIXES
        ):
            continue
        for name in _imports(path):
            if not name.startswith("disaster_monitor.application"):
                continue
            if not any(
                name == allowed or name.startswith(f"{allowed}.")
                for allowed in INFRASTRUCTURE_APPLICATION_SURFACE
            ):
                violations.append(f"{path.relative_to(SRC)} imports {name}")

    assert violations == []


def test_concrete_adapters_are_constructed_only_in_composition_modules() -> None:
    concrete_names = {"StaticCountryCatalog"}
    for path in _python_files(INFRASTRUCTURE):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        concrete_names.update(
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef)
            and (node.name.endswith("Adapter") or node.name.startswith("Composite"))
        )

    allowed_modules = {"disaster_monitor.infrastructure.composition"}
    violations = []
    for path in _python_files(SRC):
        module = _module_name(path)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = (
                node.func.id
                if isinstance(node.func, ast.Name)
                else node.func.attr
                if isinstance(node.func, ast.Attribute)
                else None
            )
            if (
                name in concrete_names
                and module not in allowed_modules
                and not module.startswith(INFRASTRUCTURE_COMPOSITION_PREFIXES)
            ):
                violations.append(f"{path.relative_to(SRC)} constructs {name}")

    assert violations == []


def test_generic_application_modules_do_not_branch_on_specific_disasters() -> None:
    violations = []
    for path in _python_files(APPLICATION):
        module = _module_name(path)
        if module in DISASTER_POLICY_MODULES or module.startswith(
            "disaster_monitor.application.services.event_policies."
        ):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "Disaster"
            ):
                violations.append(f"{path.relative_to(SRC)} uses Disaster.{node.attr}")

    assert violations == []


def test_generic_incident_priority_has_no_measurement_based_event_severity_logic() -> (
    None
):
    tree = ast.parse(
        INCIDENT_PRIORITY.read_text(encoding="utf-8"), filename=str(INCIDENT_PRIORITY)
    )
    references = [
        node
        for node in ast.walk(tree)
        if (
            isinstance(node, ast.Name)
            and node.id == "MeasurementKind"
            or isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "MeasurementKind"
        )
    ]

    assert references == []


def test_memory_and_conversation_persistence_ports_remain_separate() -> None:
    conversation_imports = _imports(CONVERSATION_STORE)
    memory_imports = _imports(MEMORY_STORE)

    assert "disaster_monitor.domain.memory" not in conversation_imports
    assert "disaster_monitor.domain.conversation" not in memory_imports
    assert "disaster_monitor.domain.memory" in memory_imports


def test_fastapi_state_exposes_only_the_typed_dependency_container() -> None:
    tree = ast.parse(MAIN.read_text(encoding="utf-8"), filename=str(MAIN))
    assigned_state_attributes = {
        node.targets[0].attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Attribute)
        and isinstance(node.targets[0].value, ast.Attribute)
        and isinstance(node.targets[0].value.value, ast.Name)
        and node.targets[0].value.value.id == "app"
        and node.targets[0].value.attr == "state"
    }

    assert assigned_state_attributes == {"dependencies"}
