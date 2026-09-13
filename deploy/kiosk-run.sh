#!/usr/bin/env bash
# Run the piano ecosystem full-screen, restarting it if it dies.
#
# Started by ~/.config/autostart/piano-kiosk.desktop at graphical login. Deliberately
# *not* a systemd user unit: `sudo -u user systemctl --user` cannot reach a user bus
# when no session owns one, which is what `Failed to connect to bus: No medium found`
# means, and XDG autostart works on Cinnamon, MATE and XFCE alike.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Installed next to this script; when run from the repository, deploy/ holds both.
# shellcheck source=deploy/browser.sh
. "$HERE/browser.sh"

LOG="${XDG_STATE_HOME:-$HOME/.local/state}/piano-kiosk.log"
mkdir -p "$(dirname "$LOG")"

log() { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >>"$LOG"; }

# A kill switch that needs no session: create this file and re-login to browse the
# notebook normally.
if [ -e "$HOME/.config/piano-kiosk.disabled" ]; then
  log "disabled by $HOME/.config/piano-kiosk.disabled; not starting"
  exit 0
fi

COMMAND="$(browser_command || true)"
if [ -z "$COMMAND" ]; then
  log "no Chromium-family browser found. On Linux Mint, install one:"
  log "  flatpak install -y flathub org.chromium.Chromium    (or Google Chrome / Brave)"
  exit 1
fi

PROFILE="$(browser_user_data_dir "$COMMAND")"
URL="${PIANO_KIOSK_URL:-http://localhost:8000}"
log "starting $(browser_label "$COMMAND") at $URL (profile $PROFILE)"

# Wait for the server so a login race does not leave a blank kiosk for a minute.
if command -v curl >/dev/null 2>&1; then
  for _ in $(seq 1 60); do
    if curl -sf -o /dev/null "$URL/api/health"; then break; fi
    sleep 1
  done
fi

while true; do
  # shellcheck disable=SC2086  # word splitting is the point: "flatpak run <app>"
  $COMMAND --kiosk --no-first-run --no-default-browser-check \
           --disable-session-crashed-bubble --user-data-dir="$PROFILE" "$URL" >>"$LOG" 2>&1
  log "browser exited ($?); restarting in 3 s"
  sleep 3
done
