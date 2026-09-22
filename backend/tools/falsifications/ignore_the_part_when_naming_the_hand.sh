#!/usr/bin/env bash
#
# Break: decide the hand from the position of the staff, ignoring the part entirely.
#
# This is the rule the renderer actually shipped, stated as the smallest possible
# version of it: `handForPart` stops reading the id and the name and returns the
# positional guess. Every unit case except the two-hand configuration must fail.
#
# The check is the unit suite, which needs no browser:
#
#   backend/tools/falsify.sh \
#     backend/tools/falsifications/ignore_the_part_when_naming_the_hand.sh \
#     "cd frontend && npm test" \
#     --expect "expected: 'LH'"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/frontend/src/lib/score.ts"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = """  const identifier = String(id ?? '').toUpperCase();
  const name = String(partName ?? '').toLowerCase();
  if (identifier.startsWith('RH') || name.includes('right')) return 'RH';
  if (identifier.startsWith('LH') || name.includes('left')) return 'LH';
  return index === 0 ? 'RH' : 'LH';"""
assert needle in text, "the hand rule is not where this script expects it"
path.write_text(text.replace(needle, "  return index === 0 ? 'RH' : 'LH';", 1))
PY
