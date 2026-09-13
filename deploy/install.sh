#!/usr/bin/env bash
# Install the piano ecosystem as a service on this machine.
#
# Run with sudo from anywhere: it copies files into system paths, builds the client,
# creates the virtualenv and enables the units. Idempotent — re-running it is how you
# upgrade.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_USER="${SERVICE_USER:-${SUDO_USER:-$(id -un)}}"
PORT="${PORT:-8000}"
DATA_DIR="${DATA_DIR:-/home/$SERVICE_USER/.local/share/piano-ecosystem}"
SERVICE_GROUP="$(id -gn "$SERVICE_USER")"
CHECK_ONLY=0
[ "${1:-}" = "--check" ] && CHECK_ONLY=1

# Every address another machine on the network can use.
#
# The old closing line printed `http://$(hostname).local:$PORT` unconditionally, which
# is only true when avahi is running *and* the other machine resolves mDNS. Reporting
# an address that does not work is worse than reporting none, so both the IPs and the
# .local name are checked and labelled.
lan_urls() {
  local port="$1" ip name out=""
  if command -v ip >/dev/null 2>&1; then
    # Interface names, so container and VM bridges are skipped: on a machine running
    # docker, `hostname -I` lists six unreachable addresses and hides the one that
    # matters.
    while read -r name ip; do
      case "$name" in
        docker*|br-*|virbr*|veth*|tun*|tap*|zt*|tailscale*|wg*) continue ;;
      esac
      case "$ip" in
        *:*) continue ;;
      esac
      out="$out http://$ip:$port"
    done <<EOF
$(ip -4 -o addr show scope global 2>/dev/null | awk '{print $2, $4}' | cut -d/ -f1)
EOF
  fi
  if [ -z "$out" ] && command -v hostname >/dev/null 2>&1; then
    for ip in $(hostname -I 2>/dev/null); do
      case "$ip" in *:*) continue ;; esac
      out="$out http://$ip:$port"
    done
  fi
  printf '%s' "${out# }"
}

mdns_name() {
  if systemctl is-active --quiet avahi-daemon 2>/dev/null; then
    printf 'http://%s.local:%s' "$(hostname)" "$1"
  fi
}

# shellcheck source=deploy/browser.sh
. "$APP_DIR/deploy/browser.sh"

BROWSER="$(browser_command || true)"
POLICY_DIR="$(browser_policy_dir "$BROWSER" || true)"

if [ "$CHECK_ONLY" = 1 ]; then
  echo "app dir        : $APP_DIR"
  echo "service user   : $SERVICE_USER ($SERVICE_GROUP)"
  echo "port           : $PORT"
  echo "data directory : $DATA_DIR"
  echo "browser        : $(browser_label "$BROWSER")"
  echo "  command      : ${BROWSER:-<none>}"
  echo "  policy dir   : ${POLICY_DIR:-<not applicable>}"
  echo "  profile dir  : $(browser_user_data_dir "$BROWSER")"
  echo "autostart file : /home/$SERVICE_USER/.config/autostart/piano-kiosk.desktop"
  echo "python3        : $(command -v python3 || echo MISSING)"
  echo "node           : $(command -v node || echo MISSING)"
  echo "curl           : $(command -v curl || echo MISSING)"
  echo "reachable from : $(lan_urls "$PORT")"
  if [ -n "$(mdns_name "$PORT")" ]; then
    echo "mDNS name      : $(mdns_name "$PORT")"
  else
    echo "mDNS name      : none (avahi-daemon not running; use the IP above)"
  fi
  [ -z "$BROWSER" ] && echo "note           : no Chromium-family browser; the kiosk will not start"
  exit 0
fi

if [[ $EUID -ne 0 ]]; then
  echo "Run with sudo: it installs a systemd unit, a browser policy and an autostart entry." >&2
  echo "Use --check first to see what it would do, without writing anything." >&2
  exit 1
fi

echo "==> Installing from $APP_DIR for user $SERVICE_USER"

command -v python3 >/dev/null || { echo "python3 is required" >&2; exit 1; }
command -v node >/dev/null || { echo "node is required to build the client" >&2; exit 1; }

if [ -z "$BROWSER" ]; then
  echo "warning: no Chromium-family browser found, so the kiosk cannot start." >&2
  echo "         Linux Mint ships no chromium package; install one of:" >&2
  echo "           flatpak install -y flathub org.chromium.Chromium" >&2
  echo "           # or Google Chrome / Brave from their .deb" >&2
  echo "         Re-run this script afterwards; nothing else depends on it." >&2
fi

echo "==> Backend virtualenv"
sudo -u "$SERVICE_USER" python3 -m venv "$APP_DIR/backend/.venv"
sudo -u "$SERVICE_USER" "$APP_DIR/backend/.venv/bin/pip" install --quiet --upgrade pip
sudo -u "$SERVICE_USER" "$APP_DIR/backend/.venv/bin/pip" install --quiet -r "$APP_DIR/backend/requirements-dev.txt"

echo "==> Frontend build"
sudo -u "$SERVICE_USER" bash -lc "cd '$APP_DIR/frontend' && npm ci && npm run build"

echo "==> Data directory"
install -d -o "$SERVICE_USER" -g "$SERVICE_GROUP" "$DATA_DIR"

echo "==> Environment file"
cat > /etc/piano-ecosystem.env <<ENV
SRT_DB_PATH=$DATA_DIR/piano.db
SRT_MEDIA_DIR=$DATA_DIR/media
SRT_LEGACY_DB=/home/$SERVICE_USER/.local/share/piano-progress/piano.db
SRT_BACKUP_DIR=$DATA_DIR/backups
SRT_BACKUP_KEEP=14
ENV

echo "==> Backups"
install -d -o "$SERVICE_USER" -g "$SERVICE_GROUP" "$DATA_DIR/backups"
# The database is the only copy of everything, and a nightly export is the cheapest
# insurance there is. It is a JSON document, so it survives a schema change.
sed -e "s|^User=.*|User=$SERVICE_USER|" \
    -e "s|^Group=.*|Group=$SERVICE_GROUP|" \
    -e "s|/opt/piano-ecosystem|$APP_DIR|g" \
    "$APP_DIR/deploy/piano-backup.service" > /etc/systemd/system/piano-backup.service
install -m 644 "$APP_DIR/deploy/piano-backup.timer" /etc/systemd/system/piano-backup.timer
systemctl daemon-reload
systemctl enable --now piano-backup.timer
echo "    nightly at 03:10, keeping $DATA_DIR/backups (14 files)"
sudo -u "$SERVICE_USER" "$APP_DIR/backend/.venv/bin/python" -m app.backup >/dev/null 2>&1 \
  && echo "    first backup written" \
  || echo "    warning: could not write a first backup; check the service log" 

echo "==> systemd unit"
sed -e "s|^User=.*|User=$SERVICE_USER|" \
    -e "s|^Group=.*|Group=$SERVICE_GROUP|" \
    -e "s|/opt/piano-ecosystem|$APP_DIR|g" \
    -e "s|--port 8000|--port $PORT|" \
    "$APP_DIR/deploy/piano-ecosystem.service" > /etc/systemd/system/piano-ecosystem.service
systemctl daemon-reload
systemctl enable --now piano-ecosystem.service

echo "==> ALSA sequencer at boot"
install -m 644 "$APP_DIR/deploy/modules-load.d/piano-midi.conf" /etc/modules-load.d/piano-midi.conf
modprobe snd_seq || echo "warning: could not load snd_seq now; it will load on the next boot" >&2

echo "==> Lid switch and idle behaviour"
install -d /etc/systemd/logind.conf.d
install -m 644 "$APP_DIR/deploy/logind/50-piano.conf" /etc/systemd/logind.conf.d/50-piano.conf
systemctl restart systemd-logind || true

echo "==> Browser policy (MIDI auto-grant, Memory Saver off)"
if [ -n "$POLICY_DIR" ]; then
  install -d "$POLICY_DIR"
  install -m 644 "$APP_DIR/deploy/chromium-policy.json" "$POLICY_DIR/piano-ecosystem.json"
  chmod -w "$POLICY_DIR"
  echo "    written to $POLICY_DIR"
elif [ -n "$BROWSER" ]; then
  # Flatpak: the sandbox cannot see /etc/chromium unless it is exposed, and path
  # exposure is not guaranteed to be honoured by every build.
  install -d /etc/chromium/policies/managed
  install -m 644 "$APP_DIR/deploy/chromium-policy.json" /etc/chromium/policies/managed/piano-ecosystem.json
  echo "    flatpak browser: attempting to expose the policy directory"
  sudo -u "$SERVICE_USER" flatpak override --user --filesystem=/etc/chromium:ro org.chromium.Chromium || true
  echo "    if the MIDI prompt still appears, click Allow once — the kiosk profile"
  echo "    remembers it, and the app shows a Connect button when it needs that."
fi

echo "==> Kiosk autostart for $SERVICE_USER"
# XDG autostart rather than a systemd user unit. `sudo -u user systemctl --user`
# cannot reach a user bus when no session owns one — that is the "Failed to connect
# to bus: No medium found" people hit on Mint — and autostart is honoured by
# Cinnamon, MATE and XFCE alike, so it also covers every Mint edition.
USER_HOME="/home/$SERVICE_USER"
BIN_DIR="$USER_HOME/.local/bin"
AUTOSTART_DIR="$USER_HOME/.config/autostart"
install -d -o "$SERVICE_USER" -g "$SERVICE_GROUP" "$BIN_DIR" "$AUTOSTART_DIR"
install -o "$SERVICE_USER" -g "$SERVICE_GROUP" -m 755 \
    "$APP_DIR/deploy/kiosk-run.sh" "$BIN_DIR/piano-kiosk.sh"
install -o "$SERVICE_USER" -g "$SERVICE_GROUP" -m 755 \
    "$APP_DIR/deploy/browser.sh" "$BIN_DIR/browser.sh"
install -o "$SERVICE_USER" -g "$SERVICE_GROUP" -m 644 \
    "$APP_DIR/deploy/piano-kiosk.desktop" "$AUTOSTART_DIR/piano-kiosk.desktop"
echo "    autostart: $AUTOSTART_DIR/piano-kiosk.desktop"
echo "    log:       $USER_HOME/.local/state/piano-kiosk.log"
echo "    disable:   touch $USER_HOME/.config/piano-kiosk.disabled"
[ -n "$BROWSER" ] || echo "    (no browser yet: autostart is in place and will work once one is installed)"

echo "==> Firewall"
if command -v ufw >/dev/null; then
  ufw allow from 192.168.0.0/16 to any port "$PORT" proto tcp || true
elif command -v firewall-cmd >/dev/null; then
  firewall-cmd --permanent --add-port="$PORT/tcp" && firewall-cmd --reload || true
else
  echo "    no ufw or firewalld found; nothing to open (Arch ships none by default)"
fi

echo
echo "Done. On this machine open http://localhost:$PORT (MIDI needs localhost)."
echo "From another machine on the LAN:"
for url in $(lan_urls "$PORT"); do echo "    $url"; done
if [ -n "$(mdns_name "$PORT")" ]; then
  echo "    $(mdns_name "$PORT")   (needs mDNS support on the other machine)"
else
  echo "    no .local name: install and start avahi-daemon to avoid typing an IP"
fi
echo
echo "Two things this script cannot do for you:"
echo "  1. Enable automatic login (Login Window / Users settings). The kiosk needs a"
echo "     graphical session, and capture stops after a reboot without one."
echo "  2. Log out and back in for the kiosk autostart to take effect."
echo
echo "Check it with:  curl -s localhost:8000/api/host"
echo "  \"sequencer\": true and CASIO in \"clients\" means the piano is visible."
echo "Kiosk log:      ~/.local/state/piano-kiosk.log"
