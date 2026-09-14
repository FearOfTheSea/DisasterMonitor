import importlib.util
from pathlib import Path

import pytest

_BACKUP_SCRIPT = Path(__file__).parents[4] / "scripts" / "operational_backup.py"
_BACKUP_SPEC = importlib.util.spec_from_file_location(
    "operational_backup_script", _BACKUP_SCRIPT
)
assert _BACKUP_SPEC is not None and _BACKUP_SPEC.loader is not None
_BACKUP_MODULE = importlib.util.module_from_spec(_BACKUP_SPEC)
_BACKUP_SPEC.loader.exec_module(_BACKUP_MODULE)
BackupError = _BACKUP_MODULE.BackupError
create_backup = _BACKUP_MODULE.create_backup
restore_backup = _BACKUP_MODULE.restore_backup
validate_backup = _BACKUP_MODULE.validate_backup


def _roots(tmp_path: Path) -> dict[str, Path]:
    roots = {
        "operational_blobs": tmp_path / "blobs",
        "event_media": tmp_path / "media",
        "ground_imagery": tmp_path / "ground",
    }
    for component, root in roots.items():
        root.mkdir(parents=True)
        (root / f"{component}.json").write_text(component, encoding="utf-8")
    return roots


def test_backup_validate_and_restore_round_trip_filesystem_components(
    tmp_path: Path,
) -> None:
    roots = _roots(tmp_path / "source")
    archive = tmp_path / "backup.tar.gz"

    create_backup(
        backup_path=archive,
        database_url=None,
        component_roots=roots,
        filesystem_only=True,
    )
    manifest = validate_backup(archive)
    assert manifest["schema_version"] == "dm.operational-backup.v2"
    assert manifest["database_contents"]
    assert manifest["database_mode"] == "filesystem_only"

    restored = _roots(tmp_path / "restored")
    for root in restored.values():
        next(root.iterdir()).write_text("old", encoding="utf-8")
    restore_backup(
        backup_path=archive,
        database_url=None,
        component_roots=restored,
        confirmation="REPLACE_OPERATIONAL_STATE",
    )
    for component, root in restored.items():
        assert next(root.iterdir()).read_text(encoding="utf-8") == component


def test_restore_requires_explicit_replacement_confirmation(tmp_path: Path) -> None:
    roots = _roots(tmp_path / "source")
    archive = tmp_path / "backup.tar.gz"
    create_backup(
        backup_path=archive,
        database_url=None,
        component_roots=roots,
        filesystem_only=True,
    )

    with pytest.raises(BackupError, match="REPLACE_OPERATIONAL_STATE"):
        restore_backup(
            backup_path=archive,
            database_url=None,
            component_roots=_roots(tmp_path / "restored"),
            confirmation="no",
        )


def test_database_restore_failure_rolls_back_filesystem_components(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _roots(tmp_path / "source")
    archive = tmp_path / "backup.tar.gz"
    monkeypatch.setattr(
        _BACKUP_MODULE,
        "_dump_database",
        lambda database_url, target: target.write_bytes(b"fixture-dump"),
    )
    create_backup(
        backup_path=archive,
        database_url="postgresql://fixture",
        component_roots=source,
        writers_paused=True,
    )
    restored = _roots(tmp_path / "restored")
    for root in restored.values():
        next(root.iterdir()).write_text("original", encoding="utf-8")

    def fail_restore(database_url: str, dump_path: Path) -> None:
        raise BackupError("fixture database restore failed")

    monkeypatch.setattr(_BACKUP_MODULE, "_restore_database", fail_restore)
    with pytest.raises(BackupError, match="database restore failed"):
        restore_backup(
            backup_path=archive,
            database_url="postgresql://fixture",
            component_roots=restored,
            confirmation="REPLACE_OPERATIONAL_STATE",
            writers_paused=True,
        )

    assert all(
        next(root.iterdir()).read_text(encoding="utf-8") == "original"
        for root in restored.values()
    )
