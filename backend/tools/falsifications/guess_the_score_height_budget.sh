#!/usr/bin/env bash
#
# Break: estimate the score's height budget from the viewport again instead of measuring the
# room the performance layout actually leaves, which is the defect this fix removed.
#
# The estimate is 150 px of chrome in focus mode; the real playing layout at 1280x600 leaves
# the score starting 290 px down. With the estimate the app fits a 16-bar score to 450 px,
# reports `fits`, and draws its last system 45 px below the fold — the one failure the whole
# mechanism exists to prevent (`docs/FEATURES.md` § 4). Nothing crashes and every other
# scenario passes; only the assertion that measures the score's bottom against the viewport
# can see it.
#
#   ./falsify.sh backend/tools/falsifications/guess_the_score_height_budget.sh \
#     "cd frontend && npm run build >/dev/null && cd .. && backend/tools/run_e2e.sh long_exercises"
# CHECK: cd frontend && npm run build >/dev/null && cd .. && backend/tools/run_e2e.sh long_exercises
# EXPECT: 16 bars fits at 1280x600 once focus mode is on
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/frontend/src/components/PracticeView.svelte"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = """    if (running && scoreContainer) {
      const top = scoreContainer.getBoundingClientRect().top;
      // A score already scrolled out of view measures as zero or negative, which would
      // become a nonsense budget; the estimate is a better answer than arithmetic on it.
      if (top > 0) {
        // The slack is sub-pixel rounding, so "fits" is never decided by half a pixel.
        return Math.max(MIN_BUDGET_PX, Math.round(window.innerHeight - top - FIT_SLACK_PX));
      }
    }
"""
assert needle in text, "the measured budget is not where this script expects it"
path.write_text(text.replace(needle, "", 1))
PY
