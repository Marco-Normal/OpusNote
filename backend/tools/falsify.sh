#!/usr/bin/env bash
#
# Prove that a check can fail.
#
#   backend/tools/falsify.sh <break-script> "<check command>" [--expect "<text the failure must mention>"]
#
#   backend/tools/falsify.sh backend/tools/falsifications/drop_pedal_sustain.sh "./check.sh --fast"
#   backend/tools/falsify.sh backend/tools/falsifications/ignore_the_part_when_naming_the_hand.sh \
#     "cd frontend && npm test" --expect "expected: 'LH'"
#
# The standing rule in docs/TEST-STRATEGY.md §8 is that no assertion is trusted until it has
# been seen to fail. A policy nobody can execute is a preference, so this makes it a command:
# apply a deliberate break, run the check that is supposed to catch it, and require that the
# check *does* fail. A check that passes with the break applied is not a check.
#
# -------------------------------------------------------------------------------------------------
# A falsification is evidence, and evidence that can be wrong in either direction is worse than no
# evidence at all: it certifies an assertion that cannot fail, or it condemns one that can and gets
# a good test weakened or deleted. So this script refuses to report an outcome it has not earned.
# The five ways the obvious implementation gets it wrong, each of them observed in this repository:
#
# 1. **A check that is already red proves nothing.** If the check fails before the break — a flaky
#    test, a misconfigured command line, a genuinely broken tree — then watching it fail after the
#    break looks exactly like a successful falsification. `exit` 1 from a mistyped command line is
#    not 126 or 127, so it lands in the "falsified" branch and certifies nothing. The check is
#    therefore run on the *unbroken* tree first and must pass. This positive control is not
#    optional, and it is why a falsification costs two runs of the check.
#
# 2. **The browser is served a build, not the source.** `frontend/dist` is gitignored, so
#    `git checkout` cannot restore it, and a break that edits `frontend/src` is invisible to a
#    check that does not rebuild. That produced a real, reproduced wrong answer here: after a
#    browser falsification the tree was clean, the source held the fix, `dist` held the *broken*
#    bundle, and the scenario still failed at 0/15 noteheads coloured. It cuts both ways — a stale
#    bundle makes a good assertion look incapable of failing, and makes a bad one look proven. So
#    this script owns the bundle: it builds before the control, builds again with the break applied
#    (so the check cannot measure stale code no matter what the check command says), and rebuilds
#    on the way out. A break that stops the project building is refused rather than reported as a
#    catch, because a build failure is not an assertion catching anything.
#
# 3. **`git checkout -- .` does not restore everything.** It reverts tracked files and leaves
#    untracked ones behind, so the tree is cleaned of untracked-but-not-ignored paths as well, and
#    the restoration is *verified* rather than assumed: if the tree is not clean afterwards, that is
#    reported loudly, because every later run would silently inherit it.
#
# 4. **An interrupted run leaves the break applied.** Restoring happens on every exit path — success,
#    failure, error, SIGINT, SIGTERM — through a trap. Two details make that actually true rather than
#    nominally true: the check runs in the background and is `wait`ed for, because bash defers a trap
#    until the foreground command returns (an interrupt during a sleeping check would otherwise leave
#    the break applied until the check finished); and cleanup kills the check and everything it
#    started *before* restoring, because a check still running is free to write to the files being
#    restored. Both were found by testing this tool against itself, not by reading it.
#
# 5. **A check that hangs certifies nothing** and blocks the operator, so it is bounded by
#    `SRT_FALSIFY_TIMEOUT` (seconds, default 1800) and a timeout is its own outcome, never a catch.
#
# The working tree must be clean, because restoring is `git checkout` and that must not be able to
# take anything else with it.
#
# `--expect TEXT` requires the failing output to contain TEXT, which turns "something failed" into
# "the assertion we meant failed". Without it any non-zero exit counts, and the script says so on
# the way past, because that is weaker evidence and the operator is entitled to know which they have.
set -uo pipefail

TIMEOUT_S="${SRT_FALSIFY_TIMEOUT:-1800}"

usage() {
  cat >&2 <<'USAGE'
usage: falsify.sh <break-script> "<check command>" [--expect "<text>"]

  <break-script>   a script under backend/tools/falsifications/ that breaks the code
  <check command>  the command that must fail while it is broken (default: ./check.sh --fast)
  --expect TEXT    require the failing output to contain TEXT, so the failure is attributed
                   to the assertion rather than to anything else going red

environment:
  SRT_FALSIFY_TIMEOUT   seconds before the check is treated as hung (default 1800)
USAGE
  echo >&2
  echo "  break scripts:" >&2
  ls "$(dirname "${BASH_SOURCE[0]}")/falsifications" 2>/dev/null | sed 's/^/    /' >&2
}

BREAK=""
CHECK=""
EXPECT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --expect) EXPECT="${2:-}"; shift 2 || shift ;;
    --expect=*) EXPECT="${1#--expect=}"; shift ;;
    -h|--help) usage; exit 0 ;;
    *)
      if [ -z "$BREAK" ]; then BREAK="$1"
      elif [ -z "$CHECK" ]; then CHECK="$1"
      else echo "unexpected argument: $1" >&2; usage; exit 2
      fi
      shift ;;
  esac
done
[ -n "$CHECK" ] || CHECK="./check.sh --fast"

if [ -z "$BREAK" ]; then usage; exit 2; fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

if [ ! -f "$BREAK" ]; then
  echo "no such break script: $BREAK" >&2
  exit 2
fi
if [ ! -x "$BREAK" ]; then
  echo "the break script is not executable: $BREAK" >&2
  echo "(chmod +x it and commit the mode, or the next run of this tool is not reproducible)" >&2
  exit 2
fi

# Does this repository have a frontend bundle that a check might be measuring instead of the source?
FRONTEND=0
if [ -f "$ROOT/frontend/package.json" ] && grep -q '"build"' "$ROOT/frontend/package.json"; then
  FRONTEND=1
fi

build_frontend() {
  ( cd "$ROOT/frontend" && npm run build ) >/dev/null 2>&1
}

#: A content-hashed listing of the served bundle, so "the bundle was restored" is a fact and not a
#: hope. `vite` names every artefact after its own contents, so an identical listing means identical
#: bytes; a difference after restoring means the bundle no longer matches the source.
bundle_manifest() {
  [ "$FRONTEND" = "1" ] || return 0
  ( cd "$ROOT/frontend" && ls dist/assets 2>/dev/null | sort )
}

BREAK_APPLIED=0
OUT=""
CHECK_PID=""
CHECK_IS_GROUP_LEADER=0
cleanup() {
  local status=$?
  # Clear the traps first: without this, a failing command inside cleanup re-enters it.
  trap - EXIT INT TERM

  # Stop the check before touching the tree. A check that is still running would otherwise be free
  # to write to the files we are about to restore, and the tree would be broken again a moment after
  # it looked clean. `timeout` runs the check in its own process group and is that group's leader,
  # so the group can be signalled as a unit; a plain signal to the leader is sent as well, in case
  # a `timeout` that could not create a group is what started it.
  if [ -n "$CHECK_PID" ] && kill -0 "$CHECK_PID" 2>/dev/null; then
    if [ "$CHECK_IS_GROUP_LEADER" = "1" ]; then
      kill -TERM -"$CHECK_PID" 2>/dev/null || true
    fi
    kill -TERM "$CHECK_PID" 2>/dev/null || true
    for _ in 1 2 3 4 5 6 7 8 9 10; do
      kill -0 "$CHECK_PID" 2>/dev/null || break
      sleep 0.2
    done
    if [ "$CHECK_IS_GROUP_LEADER" = "1" ]; then
      kill -KILL -"$CHECK_PID" 2>/dev/null || true
    fi
    kill -KILL "$CHECK_PID" 2>/dev/null || true
  fi
  CHECK_PID=""

  if [ "$BREAK_APPLIED" = "1" ]; then
    git checkout -- . >/dev/null 2>&1 || true
    # `git checkout` leaves untracked files behind. The tree was verified clean before the break,
    # so anything untracked here was created by the break or by the check and belongs to neither.
    # No `-x`: ignored paths (frontend/dist, backend/data, .scratch, mutants) are left alone.
    git clean -fdq >/dev/null 2>&1 || true
  fi

  if [ "$FRONTEND" = "1" ] && [ "$BREAK_APPLIED" = "1" ]; then
    if ! build_frontend; then
      echo "WARNING: frontend/dist could not be rebuilt; it may still hold the broken bundle." >&2
    elif [ "$BUNDLE_BEFORE" != "$(bundle_manifest)" ]; then
      echo "WARNING: frontend/dist does not match what it was before the run, even after" >&2
      echo "         rebuilding. Later browser checks would measure a different bundle." >&2
    fi
  fi

  if [ -n "$(git status --porcelain)" ]; then
    echo "WARNING: the working tree is NOT clean after restoring the break:" >&2
    git status --porcelain | sed 's/^/  /' >&2
    echo "         Every later run would inherit this. Fix it before trusting any result." >&2
  fi

  # The output is the evidence for a failure, so it is kept in that case and only discarded when
  # the run succeeded and there is nothing left to diagnose.
  if [ -n "$OUT" ] && [ -f "$OUT" ] && [ "$status" -eq 0 ]; then
    rm -f "$OUT"
  fi

  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if [ -n "$(git status --porcelain)" ]; then
  echo "refusing to start: the working tree is dirty, so the break could not be reverted" >&2
  echo "cleanly afterwards. Commit or stash first." >&2
  exit 2
fi

# The bundle must correspond to the source before anything is measured, or the control below would
# be testing one thing and the break another.
if [ "$FRONTEND" = "1" ]; then
  if ! build_frontend; then
    echo "refusing to start: the frontend does not build on the clean tree, so a check that drives" >&2
    echo "the browser would be measuring a bundle this source cannot produce." >&2
    exit 2
  fi
  BUNDLE_BEFORE="$(bundle_manifest)"
fi

OUT="$(mktemp "${TMPDIR:-/tmp}/falsify.XXXXXX")"

# Run the check in the *background* and `wait` for it, rather than in the foreground. Bash defers a
# trap until the foreground command returns, so an interrupt during a check that is sleeping, hung
# or simply slow would not run the restore until that check finished — which is precisely the case
# the trap exists for. `wait` is interruptible, so the trap runs the moment the signal arrives.
# Measured, not theorised: the first version of this ran the check in the foreground and an
# interrupted run left the break applied with the tree dirty.
#
# Not `eval`: `bash -c` takes a command *line*, which is what a check is, without eval's quoting
# traps. `bash -o pipefail` because a check written as a pipeline must report the failure of any
# stage. Stdin is /dev/null so a check that reads it cannot consume the operator's input.
run_check() {
  local runner=()
  CHECK_IS_GROUP_LEADER=0
  if command -v timeout >/dev/null 2>&1; then
    runner=(timeout "$TIMEOUT_S")
    # coreutils `timeout` puts the managed command in a fresh process group and leads it, so `$!`
    # addresses that whole group and cleanup can take down the check and everything it started.
    CHECK_IS_GROUP_LEADER=1
  fi
  ${runner[@]+"${runner[@]}"} bash -o pipefail -c "$CHECK" >"$OUT" 2>&1 </dev/null &
  CHECK_PID=$!
  local status=0
  wait "$CHECK_PID" || status=$?
  CHECK_PID=""
  return "$status"
}

echo "== control: $CHECK on the unbroken tree (it must pass) =="
run_check
control=$?

if [ "$control" -eq 124 ]; then
  echo "REFUSING TO FALSIFY: the check timed out after ${TIMEOUT_S}s on the unbroken tree." >&2
  exit 2
fi
if [ "$control" -ne 0 ]; then
  echo >&2
  echo "REFUSING TO FALSIFY: the check is already failing on the unbroken tree (exit $control)." >&2
  echo "A failure with the break applied would therefore prove nothing about the assertion —" >&2
  echo "it would only show that something was already red. Fix the check first." >&2
  echo >&2
  echo "what it reported:" >&2
  tail -15 "$OUT" | sed 's/^/  /' >&2
  echo >&2
  echo "output kept at $OUT" >&2
  exit 2
fi
echo "   control passed"

if ! "$BREAK"; then
  echo "the break script failed to apply; nothing was run" >&2
  exit 2
fi

# Set before the "changed anything" test, so that even a break which touches files and puts them back
# is restored on the way out. Restoring twice is harmless; restoring zero times is not.
BREAK_APPLIED=1

if [ -z "$(git status --porcelain)" ]; then
  echo "the break script changed nothing, so there is nothing to falsify" >&2
  echo "(a break that only writes ignored files shows up as no change here)" >&2
  exit 2
fi

echo
echo "break applied:"
git diff --stat | tail -3
git status --porcelain | grep '^??' | sed 's/^/  new file: /' || true

if [ "$FRONTEND" = "1" ]; then
  echo
  echo "== building with the break applied, so the check cannot measure a stale bundle =="
  if ! build_frontend; then
    echo >&2
    echo "REFUSING TO FALSIFY: the project does not build with the break applied." >&2
    echo "The check would fail because the build failed, not because an assertion caught the break," >&2
    echo "so the result would not be evidence about the assertion." >&2
    exit 2
  fi
fi

echo
echo "== running: $CHECK =="
run_check
status=$?

if [ "$status" -eq 124 ]; then
  echo "THE CHECK TIMED OUT after ${TIMEOUT_S}s, so nothing was falsified." >&2
  echo "A check that hangs cannot certify anything. Output kept at $OUT" >&2
  exit 2
fi

# 126 and 127 mean "found but not executable" and "not found". The check never ran, so this proves
# nothing either way, and reporting it as a falsification would be worse than useless.
if [ "$status" -eq 126 ] || [ "$status" -eq 127 ]; then
  echo "THE CHECK DID NOT RUN (exit $status), so nothing was falsified." >&2
  echo "Command was: $CHECK" >&2
  exit 2
fi

if [ "$status" -eq 0 ]; then
  echo
  echo "FALSIFICATION FAILED: the check passed with the break applied."
  echo "Either the check cannot fail, or the break was not the one it guards."
  echo "Output kept at $OUT"
  exit 1
fi

# A non-zero exit says something failed, not that the right thing failed. When the operator has
# named the text they expect, hold the run to it.
if [ -n "$EXPECT" ]; then
  if ! grep -qF -- "$EXPECT" "$OUT"; then
    echo >&2
    echo "THE CHECK FAILED, BUT NOT FOR THE REASON NAMED." >&2
    echo "It exited $status, and its output never contains: $EXPECT" >&2
    echo "So this failure cannot be attributed to the assertion the break is meant to test —" >&2
    echo "something else went red, and the assertion may still be incapable of failing." >&2
    echo "Output kept at $OUT" >&2
    exit 1
  fi
  echo
  echo "the failure names what it was expected to name: $EXPECT"
else
  echo
  echo "note: no --expect was given, so any non-zero exit was accepted as the catch. That is"
  echo "      weaker evidence than naming the assertion; pass --expect TEXT to require it."
fi

echo
echo "falsified: the check caught the break (exit $status), and the tree is restored."
echo "what it reported:"
tail -5 "$OUT" | sed 's/^/  /'
