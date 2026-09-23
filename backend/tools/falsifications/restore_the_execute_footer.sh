#!/usr/bin/env bash
#
# Break: put a "Next step: execute" footer back on a plan that has already landed.
#
# `check_docs.py`'s footer check must catch it. Four landed plans carried exactly this line, and it
# is an instruction to a later agent to re-run finished work — the most expensive kind of stale
# documentation, because obeying it is destructive rather than merely misleading.
#
# CHECK: backend/.venv/bin/python backend/tools/check_docs.py
# EXPECT: Next step
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/docs/PLAN-PHASE21.md"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
assert "**Status: landed**" in text, "PLAN-PHASE21 is not landed, so this break proves nothing"
path.write_text(
    text.rstrip("\n")
    + "\n\n**Next step:** execute with the `executing-plans` skill.\n"
)
PY
