#!/usr/bin/env bash
#
# Break: let a document claim to be history without saying whether the work landed.
#
# A current rule and a superseded one read identically to anyone who is not already an expert, and
# this repository has paid for that once already: `FEATURES.md` documented a fixed 8-second segment
# gap for two phases after the rule replacing it landed, and four landed plans still said
# `planned`. Neither broke a test, because no test can read a stale claim.
#
# So history is marked and the marking is checked. `AGENTS.md` declares which paths are records
# rather than specifications; `check_docs.py` requires that anything carrying the closing
# historical-record banner also carries a `Status:`, so a reader can always tell whether they are
# looking at finished work. This break strips 20e's status line while leaving the banner, which is
# exactly the ambiguous document the gate exists to refuse.
#
# The check that must catch it is `check_docs.py`'s historical-marker gate.
#
#   backend/tools/falsify.sh backend/tools/falsifications/unmark_a_historical_record.sh
# CHECK: backend/.venv/bin/python backend/tools/check_docs.py
# EXPECT: declares no `Status:`
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/docs/PLAN-PHASE20E.md"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()

banner = "<!-- historical-record -->"
assert banner in text, "the historical-record banner is not where this script expects it"

needle = "**Status: landed**"
assert needle in text, "the status line is not where this script expects it"
text = text.replace(needle, "**Delivered in Phase 20.**", 1)

path.write_text(text)
PY
