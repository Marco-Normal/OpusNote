# Deploying on the piano notebook

Target: a notebook that stays with the piano, running this app as a service, with a
browser as the only thing that touches MIDI.

The reasoning behind each choice is in
[`../docs/ECOSYSTEM.md`](../docs/ECOSYSTEM.md) §10 and the operational detail in
[`../docs/DEPLOYMENT.md`](../docs/DEPLOYMENT.md). This page is the checklist.

## One-time, on the notebook

```bash
sudo apt install -y python3-venv nodejs
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

1. Set the notebook to **log in automatically** — the kiosk runs inside a graphical
   session. Leave the screen-blanking setting alone: a blanked screen does not stop
   capture.
2. Check it:
   ```bash
   systemctl status piano-ecosystem
   curl -s localhost:8000/api/host
   ```
   `"sequencer": true` and `CASIO` in `"clients"` means the piano is visible to the
   server. If `clients` only lists `System` and `Midi Through`, the piano is not
   attached (or is switched off).
3. From the main computer, open `http://<notebook>.local:8000`.

## What runs where, and why

| Piece | Where | Why |
| --- | --- | --- |
| uvicorn | system service | survives reboots and crashes |
| Chromium kiosk | user session | Web MIDI needs a browser, and MIDI needs `localhost` |
| capture | that browser tab | one capture path; the page reports a heartbeat |
| MIDI permission | managed Chromium policy | no prompt on a machine nobody is sitting at |
| `snd_seq` | `modules-load.d` | without it Web MIDI finds *no* devices at all |
| kiosk autostart | `~/.config/autostart/` | **not** a systemd user unit: `sudo -u user systemctl --user` has no user bus to talk to — that is what `Failed to connect to bus: No medium found` means — and XDG autostart works on Cinnamon, MATE and XFCE alike |

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

- **Upgrade:** `git pull && sudo ./deploy/install.sh`.
- **Is it logging?** On any machine, open the Log tab: the **Capture** tile shows the
  origin that last checked in and how long ago the last note arrived. Or
  `curl -s localhost:8000/api/practice/status`.
- **Backup:** from the main computer, Log → *Export & backup* → *Download backup*
  (JSON; recording files are not inside it), and copy `media/` separately with
  `rsync -a`. See [`../docs/DEPLOYMENT.md`](../docs/DEPLOYMENT.md) for the WAL caveat
  that makes a bare copy of `piano.db` a silently truncated backup.
- **The kiosk died:** `tail ~/.local/state/piano-kiosk.log`, and `pgrep -af kiosk-run`.
  The wrapper restarts the browser if it exits, so a crash self-heals; if the wrapper
  itself is gone the capture tile goes quiet, which is the point of the heartbeat.
- **Browsing the notebook normally:** `touch ~/.config/piano-kiosk.disabled` and log
  out and back in. Delete the file to get the kiosk back.
- **Stopping it for a while:** remove `~/.config/autostart/piano-kiosk.desktop`.
- **Deleting is refused from the main computer** with a message naming
  `http://localhost:8000`. That is deliberate: read, listen, upload, edit and tag work
  over the LAN; discarding data does not.
