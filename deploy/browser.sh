# Resolve a Chromium-family browser, its policy directory and its profile directory.
#
# Sourced by both install.sh and kiosk-run.sh so the two can never disagree. Linux
# Mint is the reason this exists: it ships no chromium package at all (Chromium is a
# flatpak there), and Ubuntu's chromium package reads policies from
# /etc/chromium-browser/policies rather than Chromium's own /etc/chromium/policies.

# Echo the command to launch, or nothing when no supported browser is installed.
browser_command() {
  local candidate
  for candidate in google-chrome-stable google-chrome chromium chromium-browser \
                   brave-browser vivaldi-stable microsoft-edge-stable; do
    if command -v "$candidate" >/dev/null 2>&1; then
      echo "$candidate"
      return 0
    fi
  done
  if command -v flatpak >/dev/null 2>&1 && flatpak info org.chromium.Chromium >/dev/null 2>&1; then
    echo "flatpak run org.chromium.Chromium"
    return 0
  fi
  return 1
}

# Echo the managed-policy directory for a browser command, or nothing when the
# browser cannot read one (flatpak, without an override).
browser_policy_dir() {
  case "${1:-}" in
    google-chrome*) echo /etc/opt/chrome/policies/managed ;;
    # Debian and Ubuntu repackage Chromium with their own directory; a plain
    # Chromium build uses /etc/chromium/policies. Whichever exists wins, so a
    # distro that moved the directory is still covered.
    chromium)
      if [ -d /etc/chromium-browser ]; then
        echo /etc/chromium-browser/policies/managed
      else
        echo /etc/chromium/policies/managed
      fi
      ;;
    chromium-browser) echo /etc/chromium-browser/policies/managed ;;
    brave-browser) echo /etc/brave/policies/managed ;;
    vivaldi-stable) echo /etc/vivaldi/policies/managed ;;
    microsoft-edge-stable) echo /etc/opt/edge/policies/managed ;;
    *) return 1 ;;
  esac
}

# Echo a --user-data-dir that keeps the granted MIDI permission and the capture
# switch away from the user's everyday browsing profile.
browser_user_data_dir() {
  case "${1:-}" in
    "flatpak run"*) echo "$HOME/.var/app/org.chromium.Chromium/config/piano-ecosystem-kiosk" ;;
    *) echo "$HOME/.config/piano-ecosystem-kiosk" ;;
  esac
}

# Echo a short human label for logs.
browser_label() {
  case "${1:-}" in
    "") echo "none found" ;;
    "flatpak run"*) echo "Chromium (flatpak)" ;;
    *) echo "$1" ;;
  esac
}
