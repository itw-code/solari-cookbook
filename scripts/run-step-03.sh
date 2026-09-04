#!/usr/bin/env bash
# run-step-03.sh — drive one LIVE ColdStart STEP 03 orchestration proof.
#
# The Solari API key is NEVER placed on a command line and NEVER echoed. It is
# sourced into the shell environment from `.env` and read by orchestrate.ts
# from process.env only.
#
# Run from anywhere (it cd's to the repo root):
#   bash scripts/run-step-03.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Brief confirmation the app/build are present before spending live credits.
if [ ! -f "dist/variant-app/server.js" ]; then
  echo "[run-step-03] dist/variant-app/server.js missing — run 'npm run build' first." >&2
  exit 1
fi

# Load SOLARI_API_KEY into the environment. Nothing here prints the value.
set -a
. ./.env
set +a

if [ -z "${SOLARI_API_KEY:-}" ]; then
  echo "[run-step-03] SOLARI_API_KEY not set after sourcing .env — aborting." >&2
  exit 1
fi

# Run the orchestration proof (tsx reads tsconfig.json; noEmit stays true).
exec ./node_modules/.bin/tsx src/solari/orchestrate.ts "$@"
