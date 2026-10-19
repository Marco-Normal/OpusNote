#!/usr/bin/env bash
#
# Break: put the page shell back on the laptop-era cap it outgrew.
#
# 1080 px was chosen for a window that no longer exists here. On the 1760 px window the owner
# reported, it leaves 38% of the screen as margin — the app is dense (dashboard tiles, the sitting
# timeline, the library's two columns), so the empty band is the whole of what they complained
# about. Restoring the number reproduces it exactly.
#
# The check that must catch it is the *share of the window* assertion in `scenario_practice_log`,
# measured at 1760 px rather than in pixels, which is why it can fail on the machine it was
# reported from and not only on a small display:
#
#   backend/tools/falsify.sh backend/tools/falsifications/cap_the_shell_at_a_laptop_width.sh \
#     "backend/tools/run_e2e.sh practice_log" \
#     --expect "a wide window is mostly content"
# CHECK: backend/tools/run_e2e.sh practice_log
# EXPECT: a wide window is mostly content
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/frontend/src/App.svelte"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = "max-width: 1440px;"
assert text.count(needle) == 1, "the shell width is not where this script expects it"
path.write_text(text.replace(needle, "max-width: 1080px;", 1))
PY
