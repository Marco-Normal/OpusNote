#!/usr/bin/env bash
#
# Break: accept anything `Number()` accepts as a part of a clock.
#
# This is the shipped defect: `Number('1e3')` is 1000, `Number('0x10')` is 16, and `1:99` was
# read as 159 seconds rather than refused — three ways for a typo to seek somewhere plausible
# but wrong, which is the outcome the dangling-colon rule already exists to prevent.
#
#   backend/tools/falsify.sh backend/tools/falsifications/read_a_clock_with_number.sh \
#     "cd frontend && npm test" --expect "exponent and hex notation are not times"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/frontend/src/lib/clock.ts"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = """    if (!/^\\d+$/.test(piece)) return null;
    const value = Number(piece);
    if (!Number.isFinite(value)) return null;"""
assert needle in text, "the digits-only rule is not where this script expects it"
broken = """    const value = Number(piece);
    if (!Number.isFinite(value) || value < 0) return null;"""
text = text.replace(needle, broken, 1)
tail = """    if (index > 0 && value >= 60) return null;\n"""
assert tail in text, "the remainder bound is not where this script expects it"
path.write_text(text.replace(tail, "", 1))
PY
