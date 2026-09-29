#!/usr/bin/env bash
#
# Break: stop the cross-piece journal feed carrying the catalogue number.
#
# The feed is the one place an entry is shown away from its piece, so it is the one place the name
# has to be complete: the owner's library holds two Chopin waltzes, both "Waltz". Dropping the
# column leaves the payload valid — `piece_opus` is additive with a `None` default — and the two
# entries indistinguishable.
#
#   ./falsify.sh backend/tools/falsifications/drop_the_opus_from_the_journal_feed.sh \
#     "cd backend && .venv/bin/python -m pytest -q tests/test_repertoire.py -k journal_feed"
# CHECK: cd backend && .venv/bin/python -m pytest -q tests/test_repertoire.py -k journal_feed
# EXPECT: test_the_journal_feed_names_a_piece_by_its_catalogue_number
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/repertoire/store.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = "               p.title AS piece_title, c.name AS composer_name, p.opus AS piece_opus\n"
assert text.count(needle) == 1, "the feed's select is not where this script expects it"
path.write_text(
    text.replace(
        needle,
        "               p.title AS piece_title, c.name AS composer_name\n",
        1,
    )
)
PY
