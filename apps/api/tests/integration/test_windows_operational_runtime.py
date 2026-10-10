"""Exercise the Windows CLI without pytest's event-loop policy override."""

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.postgres
@pytest.mark.skipif(sys.platform != "win32", reason="Windows event-loop boundary")
def test_windows_migration_cli_uses_a_psycopg_compatible_loop(
    postgres_dsn: str, tmp_path: Path
) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "disaster_monitor.infrastructure.operations.runtime",
            "migrate",
        ],
        env={
            **os.environ,
            "OPERATIONAL_DATABASE_URL": postgres_dsn,
            "COUNTRY_CATALOG_ROOT": str(tmp_path / "catalog"),
            "COUNTRY_CATALOG_AUTOMATIC_UPDATES": "false",
        },
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
