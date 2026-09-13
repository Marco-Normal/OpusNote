#!/usr/bin/env bash
# Cases for browser.sh — the logic that decides which browser the kiosk launches and
# which directory its policy goes in. Written because getting this wrong is exactly
# what broke a real install on Linux Mint: there is no `chromium` package there, and
# Ubuntu's chromium reads policies from a different directory than Chromium's own.
#
# Run: bash deploy/browser.test.sh
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deploy/browser.sh
. "$HERE/browser.sh"

failures=0
check() {
  if [ "$2" = "$3" ]; then
    echo "  ok   $1"
  else
    echo "  FAIL $1"
    echo "       expected [$3]"
    echo "       got      [$2]"
    failures=$((failures + 1))
  fi
}

WORK=".scratch/browser-test"
rm -rf "$WORK"
mkdir -p "$WORK"

# One directory per case, holding exactly the named stubs. A machine with a real
# browser installed then cannot make a case pass by accident. PATH is narrowed only
# inside the command substitutions below, so the tools used to *build* the stubs are
# still reachable.
stub_path() {
  local dir="$WORK/$1"; shift
  local name
  mkdir -p "$dir"
  for name in "$@"; do
    printf '#!/bin/sh\nexit 0\n' >"$dir/$name"
    chmod +x "$dir/$name"
  done
  echo "$dir"
}

CHROMIUM="$(stub_path chromium chromium)"
UBUNTU="$(stub_path ubuntu chromium-browser)"
CHROME="$(stub_path chrome google-chrome-stable)"
FLATPAK="$(stub_path flatpak flatpak)"
EMPTY="$(stub_path none)"

echo "browser detection:"
check "plain chromium is found" "$(PATH="$CHROMIUM"; browser_command)" "chromium"
check "and uses Chromium's own policy directory" \
  "$(PATH="$CHROMIUM"; browser_policy_dir "$(browser_command)")" \
  "/etc/chromium/policies/managed"

check "Debian/Ubuntu's chromium-browser is found" \
  "$(PATH="$UBUNTU"; browser_command)" "chromium-browser"
check "and uses the directory its package checks" \
  "$(PATH="$UBUNTU"; browser_policy_dir "$(browser_command)")" \
  "/etc/chromium-browser/policies/managed"

check "Google Chrome is found" \
  "$(PATH="$CHROME"; browser_command)" "google-chrome-stable"
check "and uses Chrome's policy directory" \
  "$(PATH="$CHROME"; browser_policy_dir "$(browser_command)")" \
  "/etc/opt/chrome/policies/managed"

check "no browser at all is reported as none" \
  "$(PATH="$EMPTY"; browser_command || true)" ""
check "and no policy directory is invented" \
  "$(PATH="$EMPTY"; browser_policy_dir "" || true)" ""

# Flatpak: no browser binary, but the app is installed. Linux Mint's only route to
# Chromium, so it has to work.
check "flatpak Chromium is found" \
  "$(PATH="$FLATPAK"; browser_command)" "flatpak run org.chromium.Chromium"
check "and gets a profile inside its own sandbox" \
  "$(PATH="$FLATPAK"; browser_user_data_dir "$(browser_command)")" \
  "$HOME/.var/app/org.chromium.Chromium/config/piano-ecosystem-kiosk"

rm -rf "$WORK"

if [ "$failures" -gt 0 ]; then
  echo "browser.sh: $failures case(s) failed"
  exit 1
fi
echo "browser.sh: all cases pass"
