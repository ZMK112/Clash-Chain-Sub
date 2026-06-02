#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_PATH="$ROOT_DIR/subscription_proxy.py"

if [ "${1:-}" = "--" ]; then
  shift
fi

if [ "$#" -eq 0 ]; then
  set -- --serve --lang zh --use-saved
fi

if command -v uv >/dev/null 2>&1; then
  exec uv run --with PyYAML "$SCRIPT_PATH" "$@"
fi

printf '[INFO] uv was not found. Falling back to python3.\n'
exec python3 "$SCRIPT_PATH" "$@"
