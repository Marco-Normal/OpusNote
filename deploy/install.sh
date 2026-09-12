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

if [[ $EUID -ne 0 ]]; then
  echo "Run with sudo: it installs systemd units and a browser policy." >&2
  exit 1
fi

echo "==> Installing from $APP_DIR for user $SERVICE_USER"

command -v python3 >/dev/null || { echo "python3 is required" >&2; exit 1; }
command -v node >/dev/null || { echo "node is required to build the client" >&2; exit 1; }
command -v chromium >/dev/null || echo "warning: chromium not found; the kiosk unit will fail" >&2

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
ENV

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

echo "==> Chromium policy (MIDI auto-grant, Memory Saver off)"
POLICY_DIR=/etc/chromium/policies/managed
install -d "$POLICY_DIR"
install -m 644 "$APP_DIR/deploy/chromium-policy.json" "$POLICY_DIR/piano-ecosystem.json"

echo "==> Kiosk autostart for $SERVICE_USER"
USER_UNIT_DIR="/home/$SERVICE_USER/.config/systemd/user"
install -d -o "$SERVICE_USER" -g "$SERVICE_GROUP" "$USER_UNIT_DIR"
install -o "$SERVICE_USER" -g "$SERVICE_GROUP" -m 644 \
    "$APP_DIR/deploy/piano-kiosk.service" "$USER_UNIT_DIR/piano-kiosk.service"
sudo -u "$SERVICE_USER" systemctl --user daemon-reload
sudo -u "$SERVICE_USER" systemctl --user enable piano-kiosk.service
loginctl enable-linger "$SERVICE_USER" || true

echo "==> Firewall"
if command -v ufw >/dev/null; then
  ufw allow from 192.168.0.0/16 to any port "$PORT" proto tcp || true
elif command -v firewall-cmd >/dev/null; then
  firewall-cmd --permanent --add-port="$PORT/tcp" && firewall-cmd --reload || true
else
  echo "    no ufw or firewalld found; nothing to open (Arch ships none by default)"
fi

echo
echo "Done. On this machine open http://localhost:8000 (MIDI needs localhost)."
echo "From another machine on the LAN: http://$(hostname).local:$PORT"
