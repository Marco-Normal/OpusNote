#!/usr/bin/env bash
#
# Break: accept a catalogue number that carries no number at all.
#
# `Sonata` as an opus looks like information and cannot distinguish anything, which is exactly
# the confusion the field exists to remove. With the guardrail gone the piece is stored, the
# editor's refusal never appears, and the library quietly gains a second row that reads the
# same as the first.
#
#   ./falsify.sh backend/tools/falsifications/allow_a_numberless_opus.sh \
#     "cd backend && .venv/bin/python -m pytest -q tests/test_opus.py"
# CHECK: cd backend && .venv/bin/python -m pytest -q tests/test_opus.py
# EXPECT: test_a_numberless_opus_is_a_422_that_says_what_to_do
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/repertoire/opus.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = """    if not any(character.isdigit() for character in canonical):
        return OPUS_NEEDS_A_NUMBER
    return None"""
assert needle in text, "the guardrail is not where this script expects it"
path.write_text(text.replace(needle, "    return None", 1))
PY
