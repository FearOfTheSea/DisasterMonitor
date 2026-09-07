"""Executable ownership constraints for the capability-organized application."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "src" / "disaster_monitor"


def test_application_services_are_compatibility_exports_only() -> None:
    violations = []
    for path in (ROOT / "application" / "services").rglob("*.py"):
        tree = ast.parse(path.read_text())
        if any(
            isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            for node in tree.body
        ):
            violations.append(path.name)
    assert violations == []


def test_application_consumers_do_not_require_the_complete_operational_repository() -> (
    None
):
    violations = []
    for path in (ROOT / "application").rglob("*.py"):
        if "ports" in path.parts:
            continue
        tree = ast.parse(path.read_text())
        if any(
            isinstance(node, ast.Name) and node.id == "OperationalRepository"
            for node in ast.walk(tree)
        ):
            violations.append(str(path.relative_to(ROOT)))
    assert violations == []


def test_http_routes_delegate_conversation_and_evidence_reads() -> None:
    forbidden = {"ConversationStore", "OperationalRepository", "SnapshotReader"}
    violations = []
    for path in (ROOT / "presentation" / "http").glob("*_routes.py"):
        tree = ast.parse(path.read_text())
        if any(
            isinstance(node, ast.Name) and node.id in forbidden
            for node in ast.walk(tree)
        ):
            violations.append(path.name)
    assert violations == []


def test_severity_policy_is_owned_by_domain() -> None:
    assert (ROOT / "domain" / "hazards" / "incident_priority.py").is_file()


def test_production_composition_owns_investigation_dependencies() -> None:
    for name in ("app_composition.py", "operations/runtime.py"):
        source = (ROOT / "infrastructure" / name).read_text()
        assert "report.provider_registry" not in source
        assert "report.build_agent_tools" not in source


# Explicit cross-capability collaboration; ports and boundary DTOs are shared.
CAPABILITY_DEPENDENCIES = {
    "sources": {"agent"},
    "evidence": {"agent", "sources"},
    "decision": set(),
    "learning": set(),
    "media_analysis": set(),
    "incidents": {"evidence", "sources"},
    "conversations": {"agent"},
    "ingestion": {"decision", "evidence", "incidents"},
    "investigation": {
        "agent",
        "conversations",
        "evidence",
        "incidents",
        "learning",
        "sources",
    },
    "agent": {
        "conversations",
        "decision",
        "evidence",
        "incidents",
        "investigation",
        "media_analysis",
        "sources",
    },
}


def test_application_capabilities_obey_declared_dependencies() -> None:
    from .architecture_support import imports_from_path

    violations = []
    for capability, allowed in CAPABILITY_DEPENDENCIES.items():
        for path in (ROOT / "application" / capability).rglob("*.py"):
            for module in imports_from_path(path, ROOT.parent):
                if not module.startswith("disaster_monitor.application."):
                    continue
                target = module.split(".")[2]
                if (
                    target in CAPABILITY_DEPENDENCIES
                    and target != capability
                    and target not in allowed
                ):
                    violations.append(f"{path.relative_to(ROOT)} imports {module}")
    assert violations == []
