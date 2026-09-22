#!/usr/bin/env bash
#
# Break: name the microphone allow-list `AudioCaptureAllowedForUrls` again.
#
# Chromium's capture policies are `AudioCaptureAllowed` and `AudioCaptureAllowedUrls`. The
# `...ForUrls` suffix is a content-settings shape, which is what made the invented name plausible
# next to `MidiAllowedForUrls`. A key Chromium does not define is not read, so beside
# `AudioCaptureAllowed: false` this is an allow-list of nothing: every origin, the notebook's own
# included, is refused with no dialog and no log line. On the piano machine that is one sentence —
# "the browser refused the microphone" (AGENT-LOG.md, 2026-09-20).
#
# The checks that must catch it are the seven policy cases in deploy/browser.test.sh, which
# `./check.sh --fast` now runs as its `deploy tests` step:
#
#   backend/tools/falsify.sh backend/tools/falsifications/invent_a_microphone_policy_name.sh \
#     "bash deploy/browser.test.sh"
# CHECK: bash deploy/browser.test.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/deploy/chromium-policy.json"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = '"AudioCaptureAllowedUrls":'
assert needle in text, "the microphone allow-list is not where this script expects it"
path.write_text(text.replace(needle, '"AudioCaptureAllowedForUrls":', 1))
PY
