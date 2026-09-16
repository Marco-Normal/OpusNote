#!/usr/bin/env bash
#
# Prove that a check can fail.
#
#   ./falsify.sh backend/tools/falsifications/drop_pedal_sustain.sh "./check.sh --fast"
#
# The standing rule in docs/TEST-STRATEGY.md §8 is that no assertion is trusted until it has
# been seen to fail. A policy nobody can execute is a preference, so this makes it a command:
# apply a deliberate break, run the check that is supposed to catch it, and require that the
# check *does* fail. A check that passes with the break applied is not a check.
#
# The working tree must be clean, because reverting the break is `git checkout` and that must
# not be able to take anything else with it.
set -uo pipefail

BREAK="${1:-}"
CHECK="${2:-./check.sh --fast}"

if [ -z "$BREAK" ]; then
  echo "usage: $0 <break-script> [check command]" >&2
  echo "  break scripts live in backend/tools/falsifications/" >&2
  ls "$(dirname "${BASH_SOURCE[0]}")/falsifications" 2>/dev/null | sed 's/^/    /' >&2
  exit 2
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

if [ -n "$(git status --porcelain)" ]; then
  echo "refusing to start: the working tree is dirty, so the break could not be reverted" >&2
  echo "cleanly afterwards. Commit or stash first." >&2
  exit 2
fi

if ! "$BREAK"; then
  echo "the break script failed to apply; nothing was run" >&2
  git checkout -- . 2>/dev/null
  exit 2
fi

if git diff --quiet; then
  echo "the break script changed nothing, so there is nothing to falsify" >&2
  exit 2
fi

echo "break applied:"
git diff --stat | tail -3
echo "running: $CHECK"
echo

"$CHECK" > "${TMPDIR:-/tmp}/falsify.out" 2>&1
status=$?

git checkout -- .
echo

if [ "$status" -eq 0 ]; then
  echo "FALSIFICATION FAILED: the check passed with the break applied."
  echo "Either the check cannot fail, or the break was not the one it guards."
  echo "Output kept at ${TMPDIR:-/tmp}/falsify.out"
  exit 1
fi

echo "falsified: the check caught the break (exit $status), and the tree is restored."
