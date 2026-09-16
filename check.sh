#!/usr/bin/env bash
#
# The single entry point for verification. See docs/TEST-STRATEGY.md.
#
#   ./check.sh --fast    everything that must pass after every edit (budget: 180 s)
#   ./check.sh --full    the above plus the browser, mutation and scale tiers
#
# The tiers exist because a suite nobody runs is decorative. `--fast` is a hard ceiling:
# if something cannot fit, it moves to `--full` by naming the risk it covers, rather than
# raising the number.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TIER="${1:---fast}"

if [ "$TIER" != "--fast" ] && [ "$TIER" != "--full" ]; then
  echo "usage: $0 [--fast|--full]" >&2
  exit 2
fi

backend() { (cd "$ROOT/backend" && .venv/bin/python -m "$@"); }
frontend() { (cd "$ROOT/frontend" && "$@"); }

start=$(date +%s)
step_start=$start
step() {
  local now
  now=$(date +%s)
  if [ "$step_start" != "$start" ]; then
    echo "   (${TIER} step took $((now - step_start))s)"
  fi
  echo "== $1 =="
  step_start=$now
}

step "backend tests"
backend pytest -q -m "not slow"

step "frontend tests"
frontend npm test

step "typecheck"
frontend npm run check

step "build"
frontend npm run build

if [ "$TIER" = "--full" ]; then
  # Coverage is a report and never a gate, so it does not belong in the tier that runs
  # after every edit: it re-runs the whole backend suite under instrumentation for a number
  # nobody reads mid-change. Measured, it cost over half of a 146 s fast tier, and that is
  # exactly the headroom property testing needs. A report belongs where reports are read.
  step "coverage (report only)"
  (cd "$ROOT/backend" && .venv/bin/python -m coverage run --source=app -m pytest -q >/dev/null)
  (cd "$ROOT/backend" && .venv/bin/python -m coverage report | tail -1)

  step "browser scenarios"
  "$ROOT/backend/tools/run_e2e.sh"

  # Also a report until its baseline is known — 883 tests have never been graded, so the
  # first score is a discovery rather than a verdict.
  step "mutation (report only)"
  backend mutmut run || true
  backend mutmut results | tail -20
fi

echo
echo "check.sh $TIER passed in $(( $(date +%s) - start ))s"
