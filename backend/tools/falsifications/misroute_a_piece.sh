#!/usr/bin/env bash
#
# Break: drop the entity from a repertoire route, so a piece link lands on the tab.
#
# The browser assertion that must catch it is "a piece link opens that piece" in
# scenario_bench.
#
#   ./falsify.sh backend/tools/falsifications/misroute_a_piece.sh \
#     "cd frontend && npm run build >/dev/null && cd .. && backend/tools/run_e2e.sh bench"
# CHECK: cd frontend && npm run build >/dev/null && cd .. && backend/tools/run_e2e.sh bench
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/frontend/src/lib/route.ts"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = "  return route.entity ? `${base}/${route.entity.kind}/${route.entity.id}` : base;"
assert needle in text, "the serialiser is not where this script expects it"
path.write_text(text.replace(needle, "  return base;", 1))
PY
