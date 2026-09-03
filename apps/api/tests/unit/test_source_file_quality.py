import ast
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
SOURCE_ROOTS = (
    REPOSITORY_ROOT / "apps" / "api" / "src",
    REPOSITORY_ROOT / "apps" / "api" / "scripts",
    REPOSITORY_ROOT / "apps" / "api" / "tests",
    REPOSITORY_ROOT / "apps" / "web" / "src",
    REPOSITORY_ROOT / "apps" / "web" / "scripts",
    REPOSITORY_ROOT / "apps" / "web" / "tests",
    REPOSITORY_ROOT / "scripts",
)
SOURCE_SUFFIXES = frozenset(
    {".css", ".html", ".json", ".mjs", ".ps1", ".py", ".sql", ".ts", ".tsx"}
)
GENERATED_SOURCES = frozenset(
    {
        REPOSITORY_ROOT
        / "apps"
        / "web"
        / "src"
        / "shared"
        / "api"
        / "generated"
        / "assistant.ts"
    }
)
HARD_LINE_LIMIT = 700


def _hand_maintained_source_files() -> tuple[Path, ...]:
    return tuple(
        sorted(
            path
            for root in SOURCE_ROOTS
            for path in root.rglob("*")
            if path.is_file()
            and path.suffix in SOURCE_SUFFIXES
            and path not in GENERATED_SOURCES
        )
    )


def test_hand_maintained_source_files_respect_the_hard_size_limit() -> None:
    violations = []
    for path in _hand_maintained_source_files():
        line_count = len(path.read_text(encoding="utf-8").splitlines())
        if line_count > HARD_LINE_LIMIT:
            violations.append(
                f"{path.relative_to(REPOSITORY_ROOT)} has {line_count} lines"
            )

    assert violations == [], (
        "Split each oversized file at a cohesive responsibility boundary: "
        + "; ".join(violations)
    )


def test_python_test_modules_use_shared_fixtures_instead_of_other_tests() -> None:
    test_root = REPOSITORY_ROOT / "apps" / "api" / "tests"
    violations = []
    for path in test_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported_module = node.module.rsplit(".", 1)[-1]
                if imported_module.startswith("test_"):
                    violations.append(
                        f"{path.relative_to(REPOSITORY_ROOT)} imports {node.module}"
                    )

    assert violations == [], (
        "Move reusable setup into an explicitly named fixture module: "
        + "; ".join(violations)
    )
