#!/usr/bin/env bash
#
# Break: replace the adaptive threshold with the fixed floor, so a pause that is a breath
# inside a slow passage is treated as a stop.
#
# The test that must catch it is
# `test_a_slow_passage_tolerates_a_pause_a_fast_one_would_not`: it uses one identical
# silence after a slow passage and after a fast one, so only the adaptive term can tell
# them apart. The floor tests either side of it still pass with the break applied, which is
# what makes it that test in particular rather than the file in general.
#
#   ./falsify.sh backend/tools/falsifications/drop_adaptive_gap.sh \
#     "cd backend && .venv/bin/python -m pytest -q tests/test_segment.py"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/practice/segment.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = """    if pulse_ms <= 0:
        return float(config.floor_ms)
    return min(float(config.ceiling_ms), max(float(config.floor_ms), config.multiplier * pulse_ms))"""
assert needle in text, "the threshold is not where this script expects it"
path.write_text(text.replace(needle, "    return float(config.floor_ms)", 1))
PY
