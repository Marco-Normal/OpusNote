#!/usr/bin/env bash
#
# Break: remove the floor under the sweep interval.
#
# `queue.get(timeout=0)` returns immediately, so a setting of zero — a typo in
# `/etc/piano-ecosystem.env`, which the installer writes — would turn the runner's sweep into
# a busy loop on one core: no work done, the machine warm. The clamp is one line and easy to
# delete by someone tidying "an unnecessary max()".
#
# The test that must catch it is test_a_mistyped_sweep_interval_cannot_spin, which builds a
# runner with `sweep_s=0` and requires the interval it settled on to be at least a second. It
# asserts the guard rather than watching a thread for a spin, because watching is a timing
# test and this repository counts work instead.
#
#   ./falsify.sh backend/tools/falsifications/never_floor_the_sweep_interval.sh
# CHECK: backend/.venv/bin/python -m pytest backend/tests/test_jobs.py -q
# EXPECT: test_a_mistyped_sweep_interval_cannot_spin
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/practice/jobs.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = (
    "        self._sweep_s = max(1.0, float(sweep_s if sweep_s is not None"
    " else settings.job_sweep_s))"
)
assert needle in text, "the sweep-interval floor is not where this script expects it"
path.write_text(
    text.replace(
        needle,
        "        self._sweep_s = float(sweep_s if sweep_s is not None else settings.job_sweep_s)",
        1,
    )
)
PY
