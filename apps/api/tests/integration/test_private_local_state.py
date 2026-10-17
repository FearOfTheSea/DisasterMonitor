import os

from disaster_monitor.infrastructure.private_files import (
    restrict_private_path,
    verify_private_path,
)


def test_private_permissions_are_verified_and_backup_preserves_records(tmp_path):
    path = tmp_path / "records.json"
    path.write_text('{"notes":["retained"]}')
    restrict_private_path(path, backup=True)
    assert verify_private_path(path)
    assert path.with_suffix(".json.privacy-backup").read_text() == path.read_text()
    restrict_private_path(path, backup=True)
    assert path.read_text() == '{"notes":["retained"]}'
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600


def test_private_directory_preserves_owner_and_protects_children(tmp_path):
    directory = tmp_path / "private"
    directory.mkdir()
    restrict_private_path(directory)
    assert verify_private_path(directory)
    child = directory / "existing.json"
    child.write_text('{"retained":true}')
    restrict_private_path(child, backup=True)
    assert verify_private_path(child)
    assert child.with_suffix(".json.privacy-backup").read_text() == child.read_text()
