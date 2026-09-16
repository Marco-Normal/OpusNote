#!/usr/bin/env bash
#
# Break: put the full reload back on the edit path, restoring the measured stall.
#
# `load()` awaits the matcher's leave-one-out accuracy, the machine's health and the week's
# ratings — 866 ms, 16 ms and 53 ms against the real library, against 96 ms for the totals a
# label can actually invalidate. The browser assertions that must catch it are the pair in
# scenario_practice_log: "the matcher's accuracy is not [fetched]" and "nor the machine's health".
#
# The check rebuilds the frontend first: the browser tier serves `frontend/dist`, so a source
# break that is not rebuilt is a break the browser never sees, and the check would pass for the
# wrong reason.
#
#   ./falsify.sh backend/tools/falsifications/reload_everything_after_an_edit.sh \
#     "cd frontend && npm run build >/dev/null && cd .. && backend/tools/run_e2e.sh practice_log"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/frontend/src/components/PracticeLogView.svelte"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = """      await refreshTotals();
    } catch (cause) {
      error = cause instanceof Error ? cause.message : String(cause);
    } finally {
      busy = false;
    }"""
assert needle in text, "the edit body is not where this script expects it"
replacement = """      await refreshTotals();
      await load();
    } catch (cause) {
      error = cause instanceof Error ? cause.message : String(cause);
    } finally {
      busy = false;
    }"""
path.write_text(text.replace(needle, replacement, 1))
PY
