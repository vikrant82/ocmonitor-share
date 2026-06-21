#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi

source .venv/bin/activate

if [[ ! -x .venv/bin/ocmonitor || "${OCMONITOR_REINSTALL:-0}" == "1" ]]; then
  python -m pip install -e .
fi

if [[ "${OCMONITOR_WRAPPER_DEBUG:-0}" == "1" ]]; then
  which ocmonitor
  python - <<'PY'
import ocmonitor.ui.dashboard as dashboard
print(f"dashboard.py: {dashboard.__file__}")
PY
fi

exec ocmonitor "$@"
