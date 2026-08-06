import ast
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "disaster_monitor"
DOMAIN = SRC / "domain"
APPLICATION = SRC / "application"
INFRASTRUCTURE = SRC / "infrastructure"


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

    allowed_modules = {
        "disaster_monitor.infrastructure.composition",
        "disaster_monitor.main",
    }
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
            if name in concrete_names and module not in allowed_modules:
                violations.append(f"{path.relative_to(SRC)} constructs {name}")

    assert violations == []
