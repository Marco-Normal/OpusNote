#!/usr/bin/env bash
#
# Break: stop delivering what the page is holding when it goes away.
#
# `flush()` is asynchronous and a request started in `pagehide` is cancelled with the
# document, so before this the tail of every sitting went with the page: a reload, a kiosk
# restart or a power cut silently lost everything played since the last 2 s tick, in a module
# that otherwise guarantees a failed POST is never a lost note. Nothing anywhere reported it,
# because there is no response to check and no page left to notice.
#
# Removing the listener restores exactly that state: notes keep accumulating in the client and
# simply never leave.
#
# The check that must catch it is "hiding the page hands its notes to the browser" in
# `scenario_capture_on_hide`, which sends held note-ons — deliberately not flushed by the
# periodic tick — then dispatches `pagehide` and requires a beacon.
#
#   backend/tools/falsify.sh \
#     backend/tools/falsifications/never_flush_when_the_page_is_hidden.sh \
#     "backend/tools/run_e2e.sh capture_on_hide" \
#     --expect "hiding the page hands its notes to the browser"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/frontend/src/lib/state.svelte.ts"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = "    window.addEventListener('pagehide', () => this.capture.flushOnHide());\n"
assert needle in text, "the pagehide registration is not where this script expects it"
path.write_text(text.replace(needle, "", 1))
PY
