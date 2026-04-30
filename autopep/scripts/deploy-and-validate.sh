#!/usr/bin/env bash
# Deploy the current branch end-to-end and run the prod-target gate scenario.
#
# Usage: ./scripts/deploy-and-validate.sh <phase-number>
#   e.g. ./scripts/deploy-and-validate.sh 0
#
# Steps:
#   1. drizzle db:push to prod Neon
#   2. modal deploy of changed apps (autopep_worker + any tools/<app>/modal_app.py)
#   3. vercel deploy to production
#   4. run scripts/smoke-roundtrip.ts in --target prod mode for the phase's gate scenario

set -euo pipefail

PHASE="${1:?Usage: $0 <phase-number>}"
echo "==> Deploy + validate for Phase $PHASE"

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# 1. Schema push
echo "==> Step 1/4: drizzle db:push (prod Neon)"
if [ -z "${DATABASE_URL:-}" ]; then
	echo "DATABASE_URL must be set to the prod Neon URL"; exit 1
fi
bun run db:push

# 2. Modal deploy of changed apps
echo "==> Step 2/4: modal deploy"
modal deploy modal/autopep_worker.py
# Phase-specific tool deploys are added in later phases.

# 3. Vercel deploy
echo "==> Step 3/4: vercel --prod"
if ! command -v vercel >/dev/null; then
	echo "vercel CLI not found; install with 'npm i -g vercel'"; exit 1
fi
vercel --prod --yes

# 4. Run the prod-target smoke for this phase
echo "==> Step 4/4: smoke-roundtrip --target prod"
bun run scripts/smoke-roundtrip.ts "smoke_phase_${PHASE}" --target prod

echo "==> Phase $PHASE deploy + validate green ✓"
