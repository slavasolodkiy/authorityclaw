#!/usr/bin/env bash
set -euo pipefail

: "${AUTHORITYCLAW_LLM_URL:=}"
: "${AUTHORITYCLAW_LLM_MODEL:=}"
: "${AUTHORITYCLAW_LLM_KEY:=}"
export AUTHORITYCLAW_LLM_URL AUTHORITYCLAW_LLM_MODEL AUTHORITYCLAW_LLM_KEY
export AUTHORITYCLAW_HOME="${AUTHORITYCLAW_HOME:-$PWD/authorityclaw-state}"
port="${AUTHORITYCLAW_PORT:-8765}"
host="${AUTHORITYCLAW_HOST:-127.0.0.1}"

python3 -m authorityclaw reset
python3 -u -m authorityclaw --port "$port" run --poll 2 --host "$host"
