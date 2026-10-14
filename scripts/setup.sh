#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"

if ! command -v uv >/dev/null 2>&1; then
  echo 'Install uv first, then rerun bash scripts/setup.sh.' >&2
  exit 1
fi

uv sync --locked --python "$(cat .python-version)" "$@"
.venv/bin/python --version
echo 'Python environment ready. Follow exercises/01-environment/README.md for Lean setup and checks.'
