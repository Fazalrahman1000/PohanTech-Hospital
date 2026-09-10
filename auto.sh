#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if ! command -v python3 >/dev/null 2>&1; then
  printf '%s\n' 'Python 3.12+ is required. Install python3, python3-venv and pip using your Linux package manager.' >&2
  exit 1
fi
exec python3 ./auto.py "$@"
