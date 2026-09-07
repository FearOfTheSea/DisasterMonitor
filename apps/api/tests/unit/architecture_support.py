"""Resolve static Python imports without executing project code."""

import ast
from importlib.util import resolve_name
from pathlib import Path


def imported_modules(
    source: str, *, module: str, is_package: bool = False
) -> tuple[str, ...]:
    package = module if is_package else module.rpartition(".")[0]
    result: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            result.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            name = node.module or ""
            if node.level:
                name = resolve_name("." * node.level + name, package)
            if node.module:
                result.append(name)
            else:
                result.extend(f"{name}.{alias.name}" for alias in node.names)
    return tuple(result)


def imports_from_path(path: Path, source_root: Path) -> tuple[str, ...]:
    relative = path.relative_to(source_root).with_suffix("")
    is_package = relative.name == "__init__"
    module = ".".join(relative.parts[:-1] if is_package else relative.parts)
    return imported_modules(
        path.read_text(encoding="utf-8"), module=module, is_package=is_package
    )
