import subprocess
import sys


def test_schema_app_imports_no_production_infrastructure() -> None:
    code = """
import sys
from disaster_monitor.presentation.http.api import create_schema_app

app = create_schema_app()
assert app.openapi()["paths"]["/api/v1/assistant"]["post"]
loaded = sorted(
    name for name in sys.modules if name.startswith("disaster_monitor.infrastructure")
)
assert loaded == [], loaded
"""

    result = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
