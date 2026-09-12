# Deploying on the piano notebook

Target: a notebook that stays with the piano, running this app as a service, with a
browser as the only thing that touches MIDI.

The reasoning behind each choice is in
[`../docs/ECOSYSTEM.md`](../docs/ECOSYSTEM.md) §10 and the operational detail in
[`../docs/DEPLOYMENT.md`](../docs/DEPLOYMENT.md). This page is the checklist.

## One-time, on the notebook

```bash
sudo apt install -y python3-venv nodejs chromium   # or the distro equivalent
# put the repository somewhere it can stay, e.g. /opt/piano-ecosystem
sudo SERVICE_USER=$USER ./deploy/install.sh
```

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

## Day two

- **Upgrade:** `git pull && sudo ./deploy/install.sh`.
- **Is it logging?** On any machine, open the Log tab: the **Capture** tile shows the
  origin that last checked in and how long ago the last note arrived. Or
  `curl -s localhost:8000/api/practice/status`.
- **Backup:** from the main computer, Log → *Export & backup* → *Download backup*
  (JSON; recording files are not inside it), and copy `media/` separately with
  `rsync -a`. See [`../docs/DEPLOYMENT.md`](../docs/DEPLOYMENT.md) for the WAL caveat
  that makes a bare copy of `piano.db` a silently truncated backup.
- **The kiosk died:** `systemctl --user status piano-kiosk`. It is `Restart=always`,
  and when it cannot restart the capture tile goes quiet — which is the point of the
  heartbeat.
- **Deleting is refused from the main computer** with a message naming
  `http://localhost:8000`. That is deliberate: read, listen, upload, edit and tag work
  over the LAN; discarding data does not.
