#!/usr/bin/env bash
#
# Break: put the aggregated join back in the dashboard's sitting list.
#
# This is the state before the fix: `LEFT JOIN note_events ... GROUP BY s.id` with `LIMIT` on the
# outside, so the aggregate groups every note event in the database and sorts the result with a
# temp B-tree *before* the limit applies — a flat 65 ms on the owner's 512k-note library whether
# the list asks for one row or a thousand. The test that must catch it is
# test_listing_the_newest_sittings_does_not_read_the_older_ones, which counts work: with the join
# back, 400 notes added to a sitting the list does not return take it from 986 to 6,173 VM steps.
#
#   ./falsify.sh backend/tools/falsifications/read_every_note_to_list_sittings.sh
# CHECK: ./check.sh --fast
# EXPECT: test_listing_the_newest_sittings_does_not_read_the_older_ones
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/practice/store.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = """        WITH recent AS MATERIALIZED (
            SELECT id, started_at, ended_at, local_date, source, started_ms, ended_ms
            FROM sittings
            ORDER BY started_ms DESC
            LIMIT ?
        )
        SELECT r.id,
               r.started_at,
               r.ended_at,
               r.local_date,
               r.source,
               (SELECT COUNT(*) FROM note_events e WHERE e.sitting_id = r.id) AS note_count,
               (SELECT COUNT(*) FROM segments g WHERE g.sitting_id = r.id) AS segment_count,
               (r.ended_ms - r.started_ms) / 1000.0 AS duration_s
        FROM recent r
        ORDER BY r.started_ms DESC"""
joined = """        SELECT s.id,
               s.started_at,
               s.ended_at,
               s.local_date,
               s.source,
               COUNT(DISTINCT e.id) AS note_count,
               (SELECT COUNT(*) FROM segments g WHERE g.sitting_id = s.id) AS segment_count,
               (s.ended_ms - s.started_ms) / 1000.0 AS duration_s
        FROM sittings s
        LEFT JOIN note_events e ON e.sitting_id = s.id
        GROUP BY s.id
        ORDER BY s.started_ms DESC
        LIMIT ?"""
assert needle in text, "the materialised CTE is not where this script expects it"
path.write_text(text.replace(needle, joined, 1))
PY
