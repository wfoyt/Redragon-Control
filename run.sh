#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
task_python="$task_root/.venv/bin/python"
if [[ ! -x "$task_python" ]]; then
    task_python="/usr/bin/python3"
fi
export PYTHONPATH="$task_root${PYTHONPATH:+:$PYTHONPATH}"
exec "$task_python" -m redragon "$@"
