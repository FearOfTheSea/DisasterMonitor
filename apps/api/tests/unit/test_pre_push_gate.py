"""The local push gate must check the tree that will be published."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
HOOK = REPOSITORY_ROOT / ".githooks" / "pre-push"


def _run_hook(
    tmp_path: Path, *, dirty: bool = False, backend_fails: bool = False
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    if shutil.which("sh") is None:
        pytest.skip("The repository hook requires a POSIX shell.")
    if shutil.which("tar") is None:
        pytest.skip("The repository hook requires tar.")
    commands = tmp_path / "commands.txt"
    for name, script in {
        "git": (
            'case "$1" in\n'
            '  status) if [ "$FAKE_DIRTY" = 1 ]; then printf " M file.py\\n"; fi ;;\n'
            '  archive) exec tar -cf - -C "$FAKE_SOURCE_ROOT" '
            ".githooks/pre-push scripts/check_backend.sh "
            "scripts/check_frontend.sh apps/web/package.json ;;\n"
            "esac"
        ),
        "uv": (
            'printf "uv:%s\\n" "$PWD" >> "$FAKE_LOG"; [ "$FAKE_BACKEND_FAILURE" != 1 ]'
        ),
        "npm": 'printf "npm:%s\\n" "$PWD" >> "$FAKE_LOG"',
    }.items():
        executable = tmp_path / name
        executable.write_text(f"#!/bin/sh\n{script}\n", encoding="utf-8")
        executable.chmod(0o755)
    environment = {
        **os.environ,
        "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
        "FAKE_DIRTY": "1" if dirty else "0",
        "FAKE_BACKEND_FAILURE": "1" if backend_fails else "0",
        "FAKE_LOG": str(commands),
        "FAKE_SOURCE_ROOT": str(REPOSITORY_ROOT),
    }
    result = subprocess.run(
        ["sh", str(HOOK)],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    logged_commands = (
        commands.read_text(encoding="utf-8").splitlines() if commands.exists() else []
    )
    return result, logged_commands


def test_pre_push_refuses_to_check_an_uncommitted_tree(tmp_path: Path) -> None:
    result, commands = _run_hook(tmp_path, dirty=True)

    assert result.returncode != 0
    assert "clean working tree" in result.stderr
    assert commands == []


def test_pre_push_stops_when_backend_checks_fail(tmp_path: Path) -> None:
    result, commands = _run_hook(tmp_path, backend_fails=True)

    assert result.returncode != 0
    assert commands
    assert all(command.startswith("uv:") for command in commands)


def test_pre_push_checks_backend_before_frontend(tmp_path: Path) -> None:
    result, commands = _run_hook(tmp_path)

    assert result.returncode == 0, result.stderr
    assert any(command.startswith("uv:") for command in commands)
    assert any(command.startswith("npm:") for command in commands)
    assert min(
        index for index, command in enumerate(commands) if command.startswith("npm:")
    ) > max(
        index for index, command in enumerate(commands) if command.startswith("uv:")
    )
    assert all(
        not Path(command.split(":", 1)[1]).is_relative_to(REPOSITORY_ROOT)
        for command in commands
    )
