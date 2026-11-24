# Deploying on the piano notebook

Target: a machine that stays with the piano, running the API and headless ALSA MIDI
capture as systemd services (no GUI required for passive logging), with an optional
browser kiosk for interactive sight-reading or backwards-compatible Web MIDI capture.

The reasoning behind each choice is in
[`../docs/ECOSYSTEM.md`](../docs/ECOSYSTEM.md) §10 and the operational detail in
[`../docs/DEPLOYMENT.md`](../docs/DEPLOYMENT.md). This page is the checklist.

## One-time, on the notebook

```bash
sudo apt install -y python3-venv
# Node 23.6+ is required: the frontend tests are TypeScript, which older Node cannot
# load, and `npm run build` needs it. Distro `nodejs` predates that on Mint and
# Ubuntu — install from nodejs.org, nvm or a tarball, and check `node --version`.
# `install.sh` only checks that `node` exists, not its version.
# put the repository somewhere it can stay, e.g. /opt/piano-ecosystem
bash ./deploy/install.sh --check      # no root, writes nothing: says what it found
sudo SERVICE_USER=$USER ./deploy/install.sh
```

**Linux Mint has no `chromium` package** — Mint dropped it when Ubuntu's became a
snap stub. Install a Chromium-family browser first, because Web MIDI does not exist
in Firefox:

```bash
flatpak install -y flathub org.chromium.Chromium   # what Software Manager offers
# or Google Chrome / Brave from their .deb, or Microsoft Edge
```

`--check` reports which browser it found, and the installer still sets everything
else up if you have not chosen one yet: the autostart entry is in place and starts
working once a browser exists.

Then:

1. Check both services and ALSA visibility:
   ```bash
   systemctl status piano-ecosystem piano-midi-capture
   curl -s localhost:8000/api/host
   curl -s localhost:8000/api/practice/status
   ```
   `"sequencer": true` and `CASIO` in `"clients"` means the piano is visible to the
   server, and `capture.origin: "alsa"` with `enabled: true` means headless capture is
   active. If `clients` only lists `System` and `Midi Through`, the piano is not
   attached (or is switched off).
2. *(Optional, for interactive sight-reading or legacy browser capture)* Set the
   machine to **log in automatically** so the kiosk starts inside a graphical session.
   When `piano-midi-capture.service` is active, the browser automatically defers passive
   logging to it so notes are never double-counted.
3. From the main computer, open one of the addresses `sudo ./deploy/install.sh
   --check` printed: `http://<notebook-ip>:8000` always works,
   `http://<hostname>.local:8000` if avahi is running. Give the notebook a DHCP
   reservation so the IP stops moving. See
   [`../docs/DEPLOYMENT.md`](../docs/DEPLOYMENT.md) § *Reaching it from another
   machine*.

## What runs where, and why

| Piece | Where | Why |
| --- | --- | --- |
| uvicorn | system service (`piano-ecosystem`) | survives reboots and crashes |
| headless capture | system service (`piano-midi-capture`) | reads ALSA sequencer ports directly via `python-rtmidi`, logs without a GUI or browser, and defers browser passive capture |
| Chromium kiosk | optional user session | Web MIDI needs a browser, and MIDI needs `localhost`; used for interactive sight-reading or fallback browser capture |
| MIDI permission | managed Chromium policy | no prompt on a machine nobody is sitting at. `MidiAllowedForUrls` is a real name on builds that gate Web MIDI behind a permission prompt; current Chromium defines no MIDI policy at all, so on the notebook it is inert — harmless, and kept for the builds where it is not |
| audio-capture permission | the same managed policy | `AudioCaptureAllowedUrls` auto-grants the microphone to `localhost`/`127.0.0.1`, and `AudioCaptureAllowed: false` turns every other origin into a silent refusal instead of a prompt — which is what makes it an allow-list rather than a question asked on a machine nobody is sitting at. The name is `AudioCaptureAllowedUrls` and **not** `AudioCaptureAllowedForUrls`: capture policies have no `...ForUrls` form, and a key Chromium does not define is not ignored with a warning — it is not read at all. That misspelling beside `AudioCaptureAllowed: false` is a policy that refuses the microphone to *every* origin, the notebook's own included, without saying so. `deploy/browser.test.sh` pins the name |
| `snd_seq` | `modules-load.d` | without it Web MIDI finds *no* devices at all |
| kiosk autostart | `~/.config/autostart/` | **not** a systemd user unit: `sudo -u user systemctl --user` has no user bus to talk to — that is what `Failed to connect to bus: No medium found` means — and XDG autostart works on Cinnamon, MATE and XFCE alike |
| nightly backup | `piano-backup.timer` | a JSON export at 03:10 with `Persistent=true`, so a machine that was off still backs up on the next boot; `SRT_BACKUP_KEEP` (14) bounds the count |

## If you are coming from an earlier attempt

The first version of this installer used a systemd **user** unit and failed at
`systemctl --user` with `Failed to connect to bus: No medium found`. It may have left
a stray unit file behind, disabled and harmless, but remove it so nothing competes
with the autostart entry:

```bash
rm -f ~/.config/systemd/user/piano-kiosk.service
systemctl --user daemon-reload 2>/dev/null || true
```

There is deliberately **no** kiosk unit in `deploy/`: one autostart mechanism, or two
of them race.

## Day two

- **Upgrade:** `git pull && sudo ./deploy/install.sh`. That reinstalls the venv,
  rebuilds the client, writes the units and **restarts the service**, which is the part
  that makes it an upgrade rather than a no-op — `systemctl enable --now` alone leaves
  the old process serving the old code. The database migrates itself on first start:
  mostly new tables and columns, but the release that packed the pedal stream rewrites
  and drops `pedal_events` once — seconds, plus one `VACUUM` that needs free space equal
  to the file ([DEPLOYMENT.md](../docs/DEPLOYMENT.md) § *A backup is versioned*). The
  installer writes a backup before the new code ever runs. A browser tab that was already open keeps the old client
  bundle in memory, so reload the kiosk afterwards:
  ```bash
  pkill -f 'user-data-dir=.*piano-ecosystem-kiosk'   # the wrapper restarts it
  ```
- **First upgrade that includes the piano sound:** fetch the samples once, on the
  notebook. Either the device bar's *Install (2 MB, once)*, or from a shell, which is
  easier on a machine with no keyboard:
  ```bash
  curl -s -X POST localhost:8000/api/audio/piano | head -c 200
  curl -s localhost:8000/api/audio/piano | grep -o '"available":[a-z]*'
  ```
  They land in `$DATA_DIR/piano`, are served at `/piano/…`, and are not in the JSON
  backup — they are two seconds to fetch again.
- **Is it logging?** On any machine, open the Log tab: the **Capture** tile shows the
  origin that last checked in and how long ago the last note arrived. Or
  `curl -s localhost:8000/api/practice/status`.
- **Backup:** from the main computer, Log → *Export & backup* → *Download backup*
  (JSON; recording files are not inside it), and copy `media/` separately with
  `rsync -a`. See [`../docs/DEPLOYMENT.md`](../docs/DEPLOYMENT.md) for the WAL caveat
  that makes a bare copy of `piano.db` a silently truncated backup.
- **The kiosk died:** `tail ~/.local/state/piano-kiosk.log`, and `pgrep -af piano-kiosk.sh`
  (the installed wrapper is `~/.local/bin/piano-kiosk.sh`, not `kiosk-run`).
  The wrapper restarts the browser if it exits, so a crash self-heals; if the wrapper
  itself is gone the capture tile goes quiet, which is the point of the heartbeat.
- **Browsing the notebook normally:** `touch ~/.config/piano-kiosk.disabled` and log
  out and back in. Delete the file to get the kiosk back.
- **Stopping it for a while:** remove `~/.config/autostart/piano-kiosk.desktop`.
- **Deleting is refused from the main computer** with a message naming
  `http://localhost:8000`. That is deliberate: read, listen, upload, edit and tag work
  over the LAN; discarding data does not.
