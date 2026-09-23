#!/usr/bin/env bash
#
# The single entry point for verification. See docs/TEST-STRATEGY.md.
#
#   ./check.sh --fast    everything that must pass after every edit (budget: 180 s)
#   ./check.sh --full    the above plus the browser, mutation and scale tiers
#   ./check.sh --falsify [filter]   every break script, run against the check it declares
#   ./check.sh --falsify-quick [filter]   the same, minus the scripts whose check is the whole
#                                   fast tier: about 10 minutes instead of 40, and it says
#                                   which ones it deferred
#
# The tiers exist because a suite nobody runs is decorative. `--fast` is a hard ceiling:
# if something cannot fit, it moves to `--full` by naming the risk it covers, rather than
# raising the number.
#
# `--falsify` is its own tier rather than part of `--full`, and for the same reason: it runs the
# check twice per break script — once on the unbroken tree as a positive control, once with the
# break applied — so a full pass is about an hour. It is the tier that keeps the other tiers
# honest, not one that can run after every edit.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TIER="${1:---fast}"
FALSIFY_FILTER="${2:-}"

case "$TIER" in
  --fast|--full|--falsify|--falsify-quick) ;;
  *) echo "usage: $0 [--fast|--full|--falsify [filter]|--falsify-quick [filter]]" >&2; exit 2 ;;
esac

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

# --------------------------------------------------------------------------------------------
# --falsify: every break script, against the check it declares
#
# docs/TEST-STRATEGY.md §8 says no assertion is trusted until it has been seen to fail. Until
# now that was executed by hand, one script at a time, with the pairing between a break and its
# check living only in the script's prose — so a break could rot into a no-op and nothing would
# notice. Each script now carries `# CHECK:` (and `# EXPECT:` where the failure must name the
# assertion), which is the same example its header already gave, made readable.
#
# The outcome that matters is `failed`: the check passed with the break applied, so the assertion
# it guards cannot fail. `refused` is the tool declining to answer — a check that is already red,
# a break that stops the build, a timeout — which is a gap to investigate rather than a defect.
# --------------------------------------------------------------------------------------------
if [ "$TIER" = "--falsify" ] || [ "$TIER" = "--falsify-quick" ]; then
  falsified=0; failed=0; refused=0; skipped=0; deferred=0
  failures=(); refusals=(); deferred_names=()
  # Each distinct check is proven green once, not once per break script. Nineteen scripts declare
  # `./check.sh --fast`, and repeating its 74 s positive control for each of them was 23 minutes of
  # identical work against byte-identical source — the difference between this tier taking an hour
  # and taking forty minutes. A check is remembered only once a script has reported `falsified` or
  # `failed`, both of which prove the control passed; a refusal is never cached, because a refusal
  # may *be* the control failing.
  declare -A CONTROL_PASSED
  for script in "$ROOT"/backend/tools/falsifications/*.sh; do
    name="$(basename "$script")"
    if [ -n "$FALSIFY_FILTER" ] && [[ "$name" != *"$FALSIFY_FILTER"* ]]; then
      continue
    fi
    if ! grep -q '^# CHECK:' "$script"; then
      echo "  no check declared   $name"
      skipped=$((skipped + 1))
      continue
    fi
    check="$(sed -n 's/^# CHECK: //p' "$script" | head -1)"
    # The broad ones are not skipped because they are unimportant — they are the assertions the
    # author could not pin to a single test file, which is worth knowing. They are deferred because
    # each costs a full 74 s fast tier twice over, and a pass that takes 40 minutes is one nobody
    # runs while working. They are named in the summary rather than silently dropped.
    if [ "$TIER" = "--falsify-quick" ] && [ "$check" = "./check.sh --fast" ]; then
      deferred=$((deferred + 1)); deferred_names+=("$name")
      continue
    fi
    trust=()
    if [ -n "${CONTROL_PASSED[$check]:-}" ]; then trust=(--control-already-passed); fi
    printf '  running             %s\n' "$name"
    # `|| status=$?` rather than a bare assignment: `set -e` aborts the whole tier when a command
    # substitution in an assignment fails, so the first script that did not report `falsified`
    # ended the run before the summary. Measured — the first full pass died at script 28 of 50
    # with exit 2 and no table, which is the one thing a coverage tier must never do.
    status=0
    out="$("$ROOT/backend/tools/falsify.sh" "$script" ${trust[@]+"${trust[@]}"} 2>&1)" || status=$?
    case "$status" in
      0) echo "  falsified           $name"; falsified=$((falsified + 1)); CONTROL_PASSED[$check]=1 ;;
      1) echo "  FAILED              $name"; failed=$((failed + 1)); failures+=("$name"); CONTROL_PASSED[$check]=1 ;;
      *) echo "  refused             $name"; refused=$((refused + 1)); refusals+=("$name") ;;
    esac
    printf '%s\n' "$out" > "/tmp/falsify-$name.log" 2>/dev/null || true
  done
  echo
  echo "falsify: $falsified falsified, $failed failed, $refused refused, $skipped undeclared"
  if [ "$deferred" -gt 0 ]; then
    echo "$deferred deferred to the full pass (their check is the whole fast tier):"
    printf '  %s\n' "${deferred_names[@]}"
  fi
  if [ "${#failures[@]}" -gt 0 ]; then
    echo "these assertions could not fail when their break was applied:" >&2
    printf '  %s\n' "${failures[@]}" >&2
  fi
  if [ "${#refusals[@]}" -gt 0 ]; then
    echo "these runs were refused, so they prove nothing either way:" >&2
    printf '  %s\n' "${refusals[@]}" >&2
  fi
  [ "$failed" -eq 0 ] || exit 1
  echo
  echo "check.sh $TIER passed in $(( $(date +%s) - start ))s"
  exit 0
fi

step "backend tests"
backend pytest -q -m "not slow"

step "frontend tests"
frontend npm test

# Plain bash and 0.2 s, and it is the only check that reads the kiosk's managed policy file.
# It went unwired while the policy named a Chromium key that does not exist, which is how the
# microphone stayed refused on the notebook with every tier green: nothing here looked at it.
step "deploy tests"
bash "$ROOT/deploy/browser.test.sh"

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
