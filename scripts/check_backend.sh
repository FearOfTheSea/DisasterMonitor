#!/bin/sh
set -eux

repository_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repository_root"

uv run --frozen --directory apps/api ruff format --check src tests scripts ../../scripts
uv run --frozen --directory apps/api ruff check src tests scripts ../../scripts
uv run --frozen --directory apps/api mypy
uv run --frozen --directory apps/api mypy scripts ../../scripts
uv run --frozen --directory apps/api python scripts/check_provider_rights.py
uv run --frozen --directory apps/api python scripts/replay_provider_corpus.py
uv run --frozen --directory apps/api python scripts/check_ground_acceptance.py
uv run --frozen --directory apps/api pytest -q
