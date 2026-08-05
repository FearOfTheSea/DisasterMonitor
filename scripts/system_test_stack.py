"""Run the real Next.js UI against a fake-model FastAPI server."""

import os
import subprocess
import sys
from pathlib import Path
from threading import Thread

import uvicorn

script_directory = Path(__file__).resolve().parent
api_src = script_directory.parent / "apps" / "api" / "src"
web_directory = script_directory.parent / "apps" / "web"
sys.path.insert(0, str(api_src))
sys.path.insert(0, str(script_directory))

from disaster_monitor.main import create_app  # noqa: E402
from disaster_monitor.infrastructure.configuration import Settings  # noqa: E402
from system_test_backend import FakeSystemModel  # noqa: E402


def main() -> int:
    api_server = uvicorn.Server(
        uvicorn.Config(
            create_app(
                settings=Settings(allowed_origins="http://127.0.0.1:4173"),
                model=FakeSystemModel(),
            ),
            host="127.0.0.1",
            port=8787,
            log_level="warning",
        )
    )
    api_thread = Thread(target=api_server.run, daemon=True)
    api_thread.start()

    npm_command = "npm.cmd" if os.name == "nt" else "npm"
    web_environment = os.environ.copy()
    web_environment["NEXT_PUBLIC_API_BASE_URL"] = "http://127.0.0.1:8787/api/v1"
    subprocess.run(
        [npm_command, "run", "build"],
        cwd=web_directory,
        env=web_environment,
        check=True,
    )
    web_process = subprocess.Popen(
        [npm_command, "run", "start", "--", "--hostname", "127.0.0.1", "--port", "4173"],
        cwd=web_directory,
        env=web_environment,
    )
    try:
        return web_process.wait()
    except KeyboardInterrupt:
        return 130
    finally:
        api_server.should_exit = True
        api_thread.join(timeout=10)
        if web_process.poll() is None:
            web_process.terminate()
            web_process.wait(timeout=10)


if __name__ == "__main__":
    raise SystemExit(main())
