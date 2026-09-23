#!/usr/bin/env bash
#
# Break: leave a plan saying `planned` after its phase has shipped.
#
# `check_docs.py`'s status check must catch it. This is the exact defect the audit found: Phase 23's
# implementation and the ECOSYSTEM row landed first, while four plan headers still read `planned`,
# and nothing anywhere compared the two documents.
#
# CHECK: backend/.venv/bin/python backend/tools/check_docs.py
# EXPECT: one of them is stale
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/docs/PLAN-PHASE22.md"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = "**Status: landed 22a–22c**"
assert needle in text, "PLAN-PHASE22's status line is not where this script expects it"
path.write_text(text.replace(needle, "**Status: planned**", 1))
PY
