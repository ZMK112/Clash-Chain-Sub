#!/usr/bin/env bash
set -euo pipefail

REPO_RAW_BASE="${CLASH_CHAIN_SUB_RAW_BASE:-https://raw.githubusercontent.com/ZMK112/Clash-Chain-Sub/main}"
APP_DIR="${CLASH_CHAIN_SUB_HOME:-$PWD/.clash-chain-sub}"
SCRIPT_PATH="$APP_DIR/subscription_proxy.py"
REQ_PATH="$APP_DIR/requirements.txt"

mkdir -p "$APP_DIR"

log() {
  printf '[INFO] %s\n' "$*"
}

fail() {
  printf '[ERROR] %s\n' "$*" >&2
  exit 1
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1
}

download() {
  local url="$1"
  local output="$2"
  if need_cmd curl; then
    curl -fsSL "$url" -o "$output"
    return
  fi
  if need_cmd wget; then
    wget -qO "$output" "$url"
    return
  fi
  fail "curl or wget is required to download project files."
}

ensure_uv() {
  if need_cmd uv; then
    return
  fi

  log "uv was not found. Installing uv with the official installer."
  if need_cmd curl; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
  elif need_cmd wget; then
    wget -qO- https://astral.sh/uv/install.sh | sh
  else
    fail "curl or wget is required to install uv."
  fi

  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  need_cmd uv || fail "uv installation completed, but uv is still not on PATH."
}

log "Downloading latest Clash Chain Subscription Proxy files."
download "$REPO_RAW_BASE/subscription_proxy.py" "$SCRIPT_PATH"
download "$REPO_RAW_BASE/requirements.txt" "$REQ_PATH"

ensure_uv

if [ "${1:-}" = "--" ]; then
  shift
fi

if [ "$#" -eq 0 ]; then
  set -- --serve --lang zh
fi

log "Starting interactive proxy subscription tool with uv."
log "Cache directory: $APP_DIR"
exec uv run --with PyYAML "$SCRIPT_PATH" "$@"
