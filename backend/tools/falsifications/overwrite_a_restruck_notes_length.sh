#!/usr/bin/env bash
#
# Break: close a note-off against the wrong note-on when a key is re-struck.
#
# This is the defect the view actually shipped. It held `Map<pitch, index>`, one slot per pitch, and
# because a key can be struck again before the first strike has been released — and because
# releases arrive oldest-first — the second release was applied to the second note-on while the
# first kept the `duration: 0` it was created with. Every held note in a repeated passage was
# therefore sent to the scorer with no length at all, and the payload stayed well-formed while it
# happened, so nothing could see it.
#
# `ScoredAttempt` fixed it with a per-pitch FIFO queue, mirroring what `midi.ts` already does one
# level down. This break restores the old behaviour: the release always lands on the note with that
# pitch that was recorded last, whatever else is still open.
#
# The check that must catch it is "a key struck twice before either release is closed
# oldest-first, both with their own length" in `frontend/src/lib/scoredAttempt.test.ts`.
#
#   backend/tools/falsify.sh backend/tools/falsifications/overwrite_a_restruck_notes_length.sh
# CHECK: cd frontend && npm test
# EXPECT: the first strike keeps the length it was actually held for
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/frontend/src/lib/scoredAttempt.ts"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
start = text.index("  release(pitch: number, durationS: number): void {")
end = text.index("\n  }", start) + len("\n  }")
replacement = """  release(pitch: number, durationS: number): void {
    for (let index = this.log.length - 1; index >= 0; index -= 1) {
      if (this.log[index].pitch !== pitch) continue;
      this.log[index].duration = durationS;
      this.open.delete(pitch);
      return;
    }
  }"""
path.write_text(text[:start] + replacement + text[end:])
PY
