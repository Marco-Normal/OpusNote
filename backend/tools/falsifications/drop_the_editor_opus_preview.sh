#!/usr/bin/env bash
#
# Break: make the editor's preview the identity function, so the field shows the mess it was
# given and the guardrail says nothing.
#
# The server still canonicalises and still refuses, so nothing is corrupted — the failure is that
# the answer arrives *after* a save instead of while the field is being filled in, which is the
# whole point of a guardrail at insert. Only the browser scenario can see it: the unit test for
# the real library's spellings is in `pieceOpus.test.ts` and this change fails that too, but the
# assertion that catches what a player experiences is the one in `scenario_repertoire`.
#
#   ./falsify.sh backend/tools/falsifications/drop_the_editor_opus_preview.sh \
#     "cd frontend && npm run build >/dev/null && cd .. && backend/tools/run_e2e.sh repertoire"
# CHECK: cd frontend && npm run build >/dev/null && cd .. && backend/tools/run_e2e.sh repertoire
# EXPECT: the opus field shows what will be stored while it is still being typed
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/frontend/src/lib/pieceOpus.ts"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = """  let text = value.split(/\\s+/).filter(Boolean).join(' ');
  if (!text) return null;"""
assert needle in text, "the preview is not where this script expects it"
path.write_text(text.replace(needle, "  const text = value.trim();\n  if (!text) return null;\n  return text;", 1))
PY
