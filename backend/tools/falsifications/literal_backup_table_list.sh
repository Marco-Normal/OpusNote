#!/usr/bin/env bash
#
# Break: replace `backup.table_names`'s `sqlite_master` query with a hand-written list.
#
# The list here is the MVP blueprint's six tables — what a list looks like the day after
# somebody adds a table and forgets this one. `backup.py`'s docstring says a hand-kept
# list is the failure mode; the export assertions in `test_backup.py` must catch a stale
# copy of it.
#
#   ./falsify.sh backend/tools/falsifications/literal_backup_table_list.sh "./check.sh --fast"
# CHECK: ./check.sh --fast
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/backup.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = '''    return [
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
            " AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]
'''
replacement = '''    return [
        "users",
        "skills",
        "user_skills",
        "exercises",
        "exercise_skills",
        "performances",
    ]
'''
assert needle in text, "the query to break is not where this script expects it"
path.write_text(text.replace(needle, replacement, 1))
PY
