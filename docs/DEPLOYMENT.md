# Deployment, backup, and moving machines

The app is designed to run as **one process on the piano machine**. That is not a
preference — Web MIDI requires a secure context, and `http://192.168.1.50` is not
one: Chrome will not hand a remote LAN page access to MIDI inputs. `localhost` is,
so the machine with the USB cable to the piano is the machine that runs the
backend.

```
piano machine                    dev machine / phone
┌──────────────────────────┐
│ uvicorn + built SPA      │◀── browser, plain HTTP over the LAN
│ ~/.local/share/piano-…   │    (viewing only: no MIDI, so no secure context needed)
│   piano.db (+ -wal/-shm) │
│   media/                 │
└──────────────────────────┘
```

## Running it on the piano machine

```bash
cd frontend && npm ci && npm run build      # produces frontend/dist
cd ../backend
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Then open `http://localhost:8000` **on that machine**. `--host 0.0.0.0` is only
needed if you also want to browse the log from another device; the capture side
works fine with `127.0.0.1`.

Two operational notes:

- **One tab.** MIDI reaches every listening tab, so two tabs both capturing would
  log the same notes twice. A single app owning capture removes the *code* path for
  that (there is one capture client), but two open tabs are still two clients.
- **The API must be up before the page.** Capture queues failed batches and
  retries, so a restart mid-sitting costs nothing; but a page loaded while the API
  is down shows the error banner until you press Retry.

## Where the data lives

| Path | What |
| --- | --- |
| `~/.local/share/piano-ecosystem/piano.db` | Every table: library, journal, media rows, sittings, note events, segments, workouts, ratings |
| `~/.local/share/piano-ecosystem/media/` | Recording files, named by content hash |

Override with `SRT_DB_PATH` and `SRT_MEDIA_DIR` (see the README's configuration
table). The legacy `~/.local/share/piano-progress/` directory is only ever read,
by the one-time importer, and is never written.

## Backup

**The database is in WAL mode**, so `piano.db` alone is not a complete backup: the
most recent commits may live in `piano.db-wal` until a checkpoint. Two safe
routes, and one tempting one that is not safe.

1. **JSON export (recommended for anything you care about).** Log → *Export &
   backup* → *Download backup*. One self-describing JSON file with every table and
   row counts, safe to copy anywhere, and it crosses schema versions with a
   version check that refuses a document it cannot honour.

   ```bash
   curl -s http://localhost:8000/api/backup/export -o backup-$(date +%F).json
   ```

2. **File copy of the whole data directory** (database *and* media), with the
   server stopped, or after an explicit checkpoint:

   ```bash
   sqlite3 ~/.local/share/piano-ecosystem/piano.db "PRAGMA wal_checkpoint(TRUNCATE);"
   cp -a ~/.local/share/piano-ecosystem ~/backups/piano-ecosystem-$(date +%F)
   ```

3. **Not safe:** copying `piano.db` while the app runs and ignoring `-wal`/`-shm`.
   That is a silently truncated backup — it restores, and it is missing the last
   session.

A useful habit: the JSON export is small (no audio), so it can go somewhere
versioned or synced. The recordings are the heavy part and almost never change;
copy `media/` with `rsync -a` and it will only move new files.

## Restoring, and moving to a new machine

On the new machine:

```bash
# 1. code and build as above
# 2. database
cp ~/backups/piano-ecosystem/piano.db ~/.local/share/piano-ecosystem/
# 3. recordings
rsync -a ~/backups/piano-ecosystem/media/ ~/.local/share/piano-ecosystem/media/
# 4. start it, and check the counts
curl -s http://localhost:8000/api/health
```

Or restore from a JSON document in the browser: **Log → Export & backup →**
choose the file → *Add what is missing* (never deletes local rows) or *Replace
everything* (empties every table first; two clicks, on purpose). The media rows
travel in the document, so after importing, copy `media/` and every recording
becomes playable again — until then they read as *pending*, not *missing*, which
is the difference between "not copied yet" and "lost".

Migrating from the two older apps is separate and one-time: **Repertoire →
Import from piano-progress** copies the library and recordings from the Rust
app's database, and the same button imports the standalone practice-logger's
practice history. Both are idempotent and never write the source, so they can be
re-run while you still use the old apps.

## Troubleshooting

| Symptom | Cause |
| --- | --- |
| "No MIDI device connected" | The page is not on `localhost`/HTTPS, or the piano is off/USB unplugged. MIDI works in Chrome, Edge and Opera; not Safari. |
| Capture shows "Not reaching the API — retrying" | The backend is down or on another port. Batches are held and resent; nothing is lost until the tab closes. |
| A recording reads *pending* | Its row came across but the file has not been copied. Import with copying on, or copy `media/`. |
| Two tabs open | Each tab captures; the same notes would be logged twice. Keep one. |
| Streak looks wrong after travelling | `local_date` is written from the browser's UTC offset *at the time of playing*, which is deliberate: it cannot be recovered later. |
