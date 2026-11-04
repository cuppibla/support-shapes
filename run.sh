#!/usr/bin/env bash
# Launch the ADK web UI with the three apps: support_agent · support_team · support_workflow
#   → http://localhost:48080
set -euo pipefail
cd "$(dirname "$0")"
source .venv/bin/activate
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"
exec adk web apps --host localhost --port "${PORT:-48080}" --reload
