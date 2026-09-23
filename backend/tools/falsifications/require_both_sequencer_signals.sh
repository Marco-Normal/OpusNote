#!/usr/bin/env bash
#
# Break: require both sequencer signals instead of either.
#
# The probe's whole point is that a container has the sequencer running and no `/dev/snd/seq`,
# so trusting only the device reports a missing kernel module on a machine that has one — the
# wrong diagnosis in the most confusing possible way. The test that must catch it is
# test_the_sequencer_probe_accepts_either_signal.
#
#   ./falsify.sh backend/tools/falsifications/require_both_sequencer_signals.sh
# CHECK: ./check.sh --fast
# EXPECT: test_the_sequencer_probe_accepts_either_signal
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/hostinfo.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = "    return SEQUENCER_PATH.exists() or SEQ_CLIENTS_PATH.exists()\n"
assert needle in text, "the probe is not where this script expects it"
broke = "    return SEQUENCER_PATH.exists() and SEQ_CLIENTS_PATH.exists()\n"
path.write_text(text.replace(needle, broke, 1))
PY
