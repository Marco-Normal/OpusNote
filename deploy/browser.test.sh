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

WORK="$(cd "$HERE/.." && pwd)/.scratch/browser-test"
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

# --- the managed policy file -------------------------------------------------
#
# A key Chromium does not define is not ignored with a warning: it is not read at all, and
# nothing — no log line, no UI, nothing on `chrome://policy` unless you go looking — says so.
# This file named the microphone allow-list `AudioCaptureAllowedForUrls`, by analogy with
# `MidiAllowedForUrls`. Chromium's capture policies are `AudioCaptureAllowed` and
# `AudioCaptureAllowedUrls`, and capture has never had a `...ForUrls` form. The allow-list
# therefore granted nothing while `AudioCaptureAllowed: false` turned prompts off, so *every*
# origin — the notebook's own included — was refused with no dialog. On the notebook that is
# one sentence: "the browser refused the microphone".
#
# The names are pinned below against Chromium's own index,
# `components/policy/resources/templates/policies.yaml` — checked at the tag the notebook runs,
# `refs/tags/152.0.7977.82`: 1544 policies, with `AudioCaptureAllowedUrls` and without
# `AudioCaptureAllowedForUrls`. Adding a policy means looking the name up there first. That lookup
# is the step whose absence shipped the bug.
POLICY="$HERE/chromium-policy.json"

policy_value() {
  python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])' "$POLICY" "$1" 2>/dev/null
}
policy_has() {
  python3 -c 'import json,sys; sys.exit(0 if sys.argv[2] in json.load(open(sys.argv[1])) else 1)' \
    "$POLICY" "$1" 2>/dev/null && echo yes || echo no
}
policy_grants() {
  python3 -c 'import json,sys; sys.exit(0 if sys.argv[2] in json.load(open(sys.argv[1])).get(sys.argv[3], []) else 1)' \
    "$POLICY" "$1" "$2" 2>/dev/null && echo yes || echo no
}

echo "the managed policy file:"
check "it is valid JSON" \
  "$(python3 -c 'import json,sys; json.load(open(sys.argv[1]))' "$POLICY" 2>/dev/null && echo ok)" \
  "ok"
check "prompts are off, so the list is the whole permission" \
  "$(policy_value AudioCaptureAllowed)" "False"
check "the microphone allow-list uses Chromium's name" \
  "$(policy_has AudioCaptureAllowedUrls)" "yes"
check "and the invented ...ForUrls spelling is not there" \
  "$(policy_has AudioCaptureAllowedForUrls)" "no"
check "the notebook's own origin is the one auto-granted" \
  "$(policy_grants http://localhost:8000 AudioCaptureAllowedUrls)" "yes"
check "and so is 127.0.0.1" \
  "$(policy_grants http://127.0.0.1:8000 AudioCaptureAllowedUrls)" "yes"
check "every key is a policy name that was looked up, not guessed" \
  "$(python3 - "$POLICY" <<'PY'
import json, sys
# `MidiAllowedForUrls` is deliberately kept: current Chromium defines no MIDI policy at all,
# so it is inert here, but it is a real name on builds that gate Web MIDI and costs nothing.
KNOWN = {"AudioCaptureAllowed", "AudioCaptureAllowedUrls", "HighEfficiencyModeEnabled", "MidiAllowedForUrls"}
print(" ".join(sorted(set(json.load(open(sys.argv[1]))) - KNOWN)) or "none")
PY
)" "none"

rm -rf "$WORK"

if [ "$failures" -gt 0 ]; then
  echo "browser.sh: $failures case(s) failed"
  exit 1
fi
echo "browser.sh: all cases pass"
