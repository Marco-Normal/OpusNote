#!/usr/bin/env bash
#
# Break: report the partial band as zero share of the span.
#
# The wiring break in the sibling script proves the value reaches the row; this one proves
# the measurement itself is tested. With the body returning zero, every caller is wired
# correctly and every figure is wrong — the tests that must catch it are
# test_the_partial_ratio_is_the_share_of_the_span_between_the_bands and
# test_the_two_pedal_ratios_partition_the_time_the_pedal_did_anything.
#
#   ./falsify.sh backend/tools/falsifications/zero_the_partial_pedal_measurement.sh \
#     "cd backend && .venv/bin/python -m pytest -q tests/test_pedal.py"
# CHECK: cd backend && .venv/bin/python -m pytest -q tests/test_pedal.py
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/practice/pedal.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = """    if span_ms <= 0:
        return 0.0"""
assert needle in text, "the partial ratio body is not where this script expects it"
path.write_text(text.replace(needle, """    if span_ms <= 0:
        return 0.0
    return 0.0""", 1))
PY
