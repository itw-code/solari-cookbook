#!/usr/bin/env bash
# run-step-06.sh — drive the LIVE ColdStart STEP 06 scorecard evaluation.
#
# The Solari + LLM keys are NEVER placed on a command line and NEVER echoed.
# They are sourced into the shell environment from `.env` and read by the
# scorecard runner from process.env only.
#
# Run from anywhere (it cd's to the repo root):
#   bash scripts/run-step-06.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Brief confirmation the app/build are present before spending live credits.
if [ ! -f "dist/variant-app/server.js" ]; then
  echo "[run-step-06] dist/variant-app/server.js missing — run 'npm run build' first." >&2
  exit 1
fi

# Load SOLARI_API_KEY / LLM_* into the environment. Nothing here prints them.
set -a
. ./.env
set +a

if [ -z "${SOLARI_API_KEY:-}" ]; then
  echo "[run-step-06] SOLARI_API_KEY not set after sourcing .env — aborting." >&2
  exit 1
fi
if [ -z "${LLM_API_KEY:-}" ]; then
  echo "[run-step-06] LLM_API_KEY not set after sourcing .env — aborting." >&2
  exit 1
fi

# Run the cost-bounded scorecard (tsx reads tsconfig.json; noEmit stays true).
exec ./node_modules/.bin/tsx src/scorecard/index.ts "$@"
