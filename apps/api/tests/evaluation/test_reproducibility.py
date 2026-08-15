import subprocess
from pathlib import Path

from disaster_monitor.evaluation.reproducibility import git_metadata


def _git(repository: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def test_git_metadata_preserves_leading_dot_in_first_dirty_path(
    tmp_path: Path,
) -> None:
    _git(tmp_path, "init", "--quiet")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    _git(tmp_path, "config", "user.name", "DisasterMonitor test")
    ignore = tmp_path / ".gitignore"
    ignore.write_text("first\n", encoding="utf-8")
    _git(tmp_path, "add", ".gitignore")
    _git(tmp_path, "commit", "--quiet", "-m", "fixture")
    ignore.write_text("first\nsecond\n", encoding="utf-8")

    metadata = git_metadata(tmp_path)

    assert metadata["dirty"] is True
    assert metadata["dirty_paths"] == (".gitignore",)
