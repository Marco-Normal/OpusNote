#!/usr/bin/env bash
#
# Break: report the per-segment band instead of the decoded one.
#
# The accuracy page is the only place a claim about the matcher is made, and it has to
# measure the scorer that writes labels. Falling back to `identify`'s band keeps every
# leave-one-out score and the top-1 count correct — it only under-reports the coverage the
# sequence adds, which is the number the change is justified by.
#
#   ./check.sh --falsify count_the_band_the_segment
# CHECK: cd backend && .venv/bin/python -m pytest -q tests/test_autotag.py -k accuracy_report
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/practice/store.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = """                band = sitting_sequence.band(
                    belief,
                    auto_probability=settings.autotag_auto_probability,
                    prompt_probability=settings.autotag_prompt_probability,
                    min_notes=settings.autotag_min_notes,
                )"""
assert text.count(needle) == 1, "the report's band is not where this script expects it"
path.write_text(text.replace(needle, "                band = ranked[segment_id].band", 1))
PY
