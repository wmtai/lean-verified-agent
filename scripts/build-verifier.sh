#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
docker build --build-arg LEAN_VERSION=4.34.1 \
  --tag lean-verified-agent-verifier:4.34.1 "$repo_dir"
