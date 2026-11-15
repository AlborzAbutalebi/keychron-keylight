#!/bin/bash
# Run Keylight from source in your browser (no app bundle needed).
set -euo pipefail
cd "$(dirname "$0")"
[[ -x .venv/bin/python ]] || { python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt; }
(sleep 1.5; open http://localhost:8787) &
exec .venv/bin/python app/keylight.py "$@"
