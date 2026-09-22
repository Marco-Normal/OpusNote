#!/usr/bin/env bash
#
# Break: restore the old silent-degradation branch in `json_load`.
#
# Malformed text goes back to returning the default, so a corrupt
# `exercises.expected_json` reads as "no expected notes" again. T9's
# `test_malformed_text_raises_and_names_the_damage` and
# `test_a_non_text_value_counts_as_damage` must fail.
#
#   ./falsify.sh backend/tools/falsifications/json_load_returns_default.sh "./check.sh --fast"
# CHECK: ./check.sh --fast
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/db.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = (
    "    except (TypeError, ValueError) as exc:\n"
    "        raise CorruptJSON(\n"
    '            f"stored JSON is corrupt ({type(exc).__name__}: {exc}): {_truncate(raw)}"\n'
    "        ) from exc\n"
)
assert needle in text, "the branch to break is not where this script expects it"
path.write_text(text.replace(needle, "    except (TypeError, ValueError):\n        return default\n", 1))
PY
