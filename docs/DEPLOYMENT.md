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

## The planted notebook, as a LAN server

The single-machine setup above is the short version. This one is for the actual
target: a notebook that lives with the piano, runs as a service, and is read from
somewhere else.

```
notebook at the piano (authoritative)        main computer / phone
┌───────────────────────────────────┐
│ piano-ecosystem.service           │◀── http://piano.local:8000
│   uvicorn 0.0.0.0:8000 + SPA      │    viewing, uploads, playback,
│   ~/.local/share/piano-ecosystem/ │    tagging — no MIDI, so plain HTTP
│     piano.db (+ -wal/-shm), media/│
│ piano-kiosk.service               │
│   chromium --kiosk localhost:8000 │  ← the only thing that touches MIDI
└───────────────────────────────────┘
```

`sudo ./deploy/install.sh` sets all of it up; [`../deploy/README.md`](../deploy/README.md)
is the checklist. The parts worth understanding rather than copying:

| Piece | Why it is there |
| --- | --- |
| Kiosk at `http://localhost:8000` | Web MIDI needs a secure context. `piano.local` is not one, so the notebook plays through localhost and the main computer reads through the LAN name |
| Kiosk started by **XDG autostart** | not a systemd user unit. `sudo -u user systemctl --user` fails with `Failed to connect to bus: No medium found`, because sudo drops `XDG_RUNTIME_DIR`/`DBUS_SESSION_BUS_ADDRESS` and a machine may have no user session at all. Autostart needs no bus and works on Cinnamon, MATE and XFCE |
| A Chromium-family browser, which Mint does not ship | Firefox has no Web MIDI. On Mint, Chromium is a flatpak (`org.chromium.Chromium`); Chrome, Brave, Vivaldi and Edge also work. `/etc/chromium/policies` is Chromium's own path — **Ubuntu and Mint packages read `/etc/chromium-browser/policies`** — so the installer picks by detected browser |
| `MidiAllowedForUrls` policy | grants the MIDI permission with no prompt — nobody is sitting there to click Allow |
| `HighEfficiencyModeEnabled: false` | stops Memory Saver *discarding* the capture tab. Throttled timers are harmless: every note carries its own absolute timestamp, so a late batch still lands in the right sitting |
| `snd_seq` in `modules-load.d` | Web MIDI enumerates the ALSA sequencer; without it the browser reports **no MIDI devices at all**, which looks exactly like broken hardware. `/api/host` reports `sequencer` so the two are distinguishable |
| `logind` drop-in | a closed lid must not suspend the machine that is doing the logging |
| `SRT_MAX_UPLOAD_MB` (512) | enforced while writing, so a mis-drag from another machine cannot fill the notebook's disk |

### What the LAN may do

No accounts, but the irreversible actions are refused off the piano machine
(ECOSYSTEM.md D8). The rule is *would this discard data*:

| Refused away from the notebook | Still fine over the LAN |
| --- | --- |
| deleting a piece, composer, journal entry or recording; resetting the profile; restoring a backup with `mode="replace"`; re-segmenting with `confirm=true` | viewing statistics, listening to recordings, uploading recordings, editing pieces and composers, tagging segments, splitting and merging, merge-imports, unlabelled re-segmenting |

A refusal is a 403 whose message names `http://localhost:8000`, and the same controls
are disabled in the interface with the reason in their tooltip, so the rule is
visible before it is hit. Note the check is on the *socket peer*
(`request.client.host` via `ipaddress`): if a reverse proxy is ever put in front, that
address becomes the proxy's and the check must move to a trusted header.

### Kiosk troubleshooting

| Symptom | Cause |
| --- | --- |
| `Failed to connect to bus: No medium found` | something ran `systemctl --user` under sudo. The installer no longer does; if you hit it by hand, use the autostart file instead |
| The kiosk never appears after login | no browser installed (`bash deploy/install.sh --check`), or automatic login is off. Check `~/.local/state/piano-kiosk.log` |
| MIDI permission dialog appears once | the browser is a flatpak and cannot read `/etc/chromium`, or a policy file landed in the wrong directory for the package. Click Allow once: the kiosk has its own profile and remembers it |
| The page loads but no notes are logged | `/api/host` → `sequencer: false` means `snd_seq` is not loaded; kill the live view and check the clients list too |

### Is the notebook actually logging?

Two independent signals, both visible from any machine in the Log tab:

- **Capture** — the origin that last checked in and how long ago the last note
  arrived. The heartbeat is ephemeral (in memory, 15 s cadence, treated as gone after
  60 s) and carries only liveness; the note timestamp comes from the database, so it
  is a fact rather than a client's claim.
- `curl -s localhost:8000/api/host` — `sequencer: true` plus `CASIO` in `clients`
  means the server can see the piano through ALSA. Only `System` and `Midi Through`
  means it cannot: either the piano is off, or `snd_seq` is missing.

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
