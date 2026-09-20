#!/usr/bin/env bash
#
# Run the browser scenarios against a server started for the purpose.
#
# The README documents this as one long command with four environment prefixes; this is
# that command, plus the wait for health and the teardown the long version leaves to the
# reader. It always uses its own database and media directory, so it can never touch the
# real practice log — the same three files `backend/tests/conftest.py` redirects.
#
# Port 8011 by default, deliberately not 8000: a test that silently drives whatever server
# happens to be running on the documented port is a test whose result depends on somebody
# else's session. Override with SRT_E2E_PORT.
#
#   ./run_e2e.sh              every scenario in the registry
#   ./run_e2e.sh playback     one scenario, by the ONLY filter
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
DATA="$ROOT/backend/data"
PORT="${SRT_E2E_PORT:-8011}"

export SRT_DB_PATH="$DATA/e2e.sqlite3"
export SRT_LEGACY_DB="$DATA/legacy-fixture.db"
export SRT_MEDIA_DIR="$DATA/e2e-media"
export SRT_PIANO_DIR="$DATA/e2e-piano"

if curl -sf -m 1 "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then
  echo "port $PORT is already serving; refusing to start a second server" >&2
  exit 1
fi

(cd "$ROOT/backend" && .venv/bin/python -m uvicorn app.main:app --port "$PORT" --host 127.0.0.1) &
server=$!
trap 'kill "$server" 2>/dev/null || true; wait "$server" 2>/dev/null || true' EXIT

for _ in $(seq 1 60); do
  if curl -sf -m 2 "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then break; fi
  sleep 1
done

if ! curl -sf -m 2 "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then
  echo "the server never became healthy on port $PORT" >&2
  exit 1
fi

cd "$ROOT/backend"
.venv/bin/python tools/e2e_browser.py "http://127.0.0.1:$PORT" "$@"
