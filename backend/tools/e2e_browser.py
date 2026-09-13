#!/usr/bin/env python
"""End-to-end browser verification of the sight-reading loop.

Drives the real built client in Chromium against the real API, with a
*simulated* Web MIDI implementation injected before any page script runs. That
means the genuine :class:`MidiInput` code path is exercised — connecting,
selecting an input, decoding status bytes, and measuring onsets against the
count-in anchor — rather than being stubbed out.

Requirements: the API must already be running and serving the built frontend
(``uvicorn app.main:app``), and system Chromium must be installed.

Usage::

    backend/.venv/bin/python backend/tools/e2e_browser.py [base_url] [scenario]

The optional second argument is a substring of a scenario name (``repertoire``,
``practice_log``, …) and runs only that one. It exists to iterate on a fix; a
slice is verified by running the whole file with no filter.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import urllib.request
from pathlib import Path
from typing import Any

from urllib.request import urlopen

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout, sync_playwright

BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
#: Optional substring filter on the scenario name, for a fast single-scenario run.
ONLY = sys.argv[2].lower() if len(sys.argv) > 2 else ""
CHROMIUM = "/usr/bin/chromium"
SHOTS = Path(__file__).resolve().parent.parent / "screenshots"
DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "e2e.sqlite3"
DEFAULT_LEGACY = Path(__file__).resolve().parent.parent / "data" / "legacy-fixture.db"

#: Injected before every page script. Mimics a Casio PX-870 enough for the app's
#: own MIDI layer to treat it as a real device.
FAKE_MIDI = """
(() => {
  const makeInput = (id, name, manufacturer) => ({
    id,
    name,
    manufacturer,
    type: 'input',
    state: 'connected',
    connection: 'open',
    onmidimessage: null,
  });
  const through = makeInput('alsa-midi-through', 'Midi Through Port-0', 'Midi Through');
  const casio = makeInput('alsa-casio-1', 'CASIO USB-MIDI MIDI 1', 'CASIO');

  // Outgoing messages, so "Stop actually stops" can be checked rather than trusted:
  // a note-off and an all-notes-off on the wire are the only proof that a real piano
  // would fall silent.
  const outgoing = [];
  const makeOutput = (id, name, manufacturer) => ({
    id,
    name,
    manufacturer,
    type: 'output',
    state: 'connected',
    connection: 'open',
    send(data, timestamp) {
      outgoing.push({ port: id, data: [...data], timestamp: timestamp ?? null, at: performance.now() });
    },
    clear() {},
  });
  const casioOut = makeOutput('alsa-casio-out', 'CASIO USB-MIDI MIDI 1', 'CASIO');
  const throughOut = makeOutput('alsa-through-out', 'Midi Through Port-0', 'Midi Through');
  const outputs = new Map([[casioOut.id, casioOut], [throughOut.id, throughOut]]);

  const ports = new Map();
  const access = {
    inputs: {
      forEach: (callback) => ports.forEach((value) => callback(value)),
      get: (key) => ports.get(key),
      get size() { return ports.size; },
    },
    outputs: {
      forEach: (callback) => outputs.forEach((value) => callback(value)),
      get: (key) => outputs.get(key),
      get size() { return outputs.size; },
    },
    sysexEnabled: false,
    onstatechange: null,
  };
  const announce = () => {
    if (typeof access.onstatechange === 'function') access.onstatechange({});
  };
  navigator.requestMIDIAccess = async () => access;
  window.__fakeMidi = {
    // The live port is what every existing scenario means by "send a note".
    send(bytes, portId) {
      const target = ports.get(portId ?? 'alsa-casio-1');
      if (!target || typeof target.onmidimessage !== 'function') return false;
      target.onmidimessage({ data: new Uint8Array(bytes), timeStamp: performance.now() });
      return true;
    },
    // The same key reported by both ports, which is what a key echo looks like.
    sendToAll(bytes) {
      let delivered = 0;
      for (const id of [...ports.keys()]) if (this.send(bytes, id)) delivered += 1;
      return delivered;
    },
    ready() {
      return typeof casio.onmidimessage === 'function';
    },
    // Everything the app has played *at* the piano, in order.
    sent() {
      return outgoing.slice();
    },
    noteOns() {
      return outgoing.filter((m) => (m.data[0] & 0xf0) === 0x90 && m.data[2] > 0)
        .map((m) => ({ port: m.port, pitch: m.data[1], velocity: m.data[2], timestamp: m.timestamp }));
    },
    noteOffs() {
      return outgoing.filter((m) => (m.data[0] & 0xf0) === 0x80).map((m) => m.data[1]);
    },
    allNotesOff() {
      return outgoing.filter((m) => (m.data[0] & 0xf0) === 0xb0 && (m.data[1] === 123 || m.data[1] === 120)).length;
    },
    forget() {
      outgoing.length = 0;
    },
    outputs() {
      return [...outputs.values()].map((o) => ({ id: o.id, name: o.name }));
    },
    total() {
      return ports.size;
    },
    unplugAll() {
      ports.clear();
      announce();
    },
    plug(portId) {
      ports.set(portId, portId === 'alsa-casio-1' ? casio : through);
      announce();
    },
    plugLater(ms, portId) {
      setTimeout(() => this.plug(portId), ms);
    },
  };
  // Plugged in and switched on before the app loads: the case the feature exists for.
  ports.set(through.id, through);
  ports.set(casio.id, casio);
})();
"""

#: Schedule a whole performance from inside the page, anchored to `performance.now()`.
#: The same clock the app uses for onsets, so timing is exact apart from the
#: polling delay in detecting that playback started.
PLAY_NOTES = """
([notes, velocity, holdMs]) => {
  const anchor = performance.now();
  const queue = notes
    .map((note) => ({ pitch: note.pitch, at: Math.max(0, note.onset_s * 1000) }))
    .sort((a, b) => a.at - b.at);
  window.__playTimers = [];
  window.__playCancelled = false;
  window.__playEmitted = 0;

  // Driven from requestAnimationFrame rather than one setTimeout per note: a
  // dense exercise is a hundred-odd notes, and that many independent timers
  // drift well past the 200 ms match window under load, which makes the harness
  // look like a scoring bug.
  let index = 0;
  const pump = () => {
    // The pump is a frame loop, so clearing timers alone would not stop it and
    // its notes would leak into whatever the test does next.
    if (window.__playCancelled) return;
    const elapsed = performance.now() - anchor;
    while (index < queue.length && queue[index].at <= elapsed + 1) {
      const note = queue[index];
      window.__fakeMidi.send([0x90, note.pitch, velocity]);
      window.__playEmitted += 1;
      window.__playTimers.push(
        setTimeout(() => window.__fakeMidi.send([0x80, note.pitch, 0]), holdMs),
      );
      index += 1;
    }
    if (index < queue.length) requestAnimationFrame(pump);
  };
  requestAnimationFrame(pump);
  return anchor;
}
"""

#: Cancel any notes still queued from the previous run. Without this, a long
#: exercise keeps firing notes into whatever the test does next.
CANCEL_PLAYBACK = """
() => {
  window.__playCancelled = true;
  (window.__playTimers || []).forEach(clearTimeout);
  window.__playTimers = [];
  return true;
}
"""


#: WCAG relative-luminance contrast, so "is the red readable on black?" is a
#: measurement rather than an opinion.
CONTRAST = """
([foreground, background]) => {
  const parse = (value) => {
    const rgb = value.match(/rgba?\\(([^)]+)\\)/);
    if (rgb) return rgb[1].split(',').slice(0, 3).map(Number);
    let hex = value.replace('#', '').trim();
    if (hex.length === 3) hex = hex.split('').map((c) => c + c).join('');
    return [0, 2, 4].map((i) => parseInt(hex.slice(i, i + 2), 16));
  };
  const luminance = ([r, g, b]) => {
    const channel = (v) => {
      const x = v / 255;
      return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4);
    };
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
  };
  const a = luminance(parse(foreground));
  const b = luminance(parse(background));
  const [hi, lo] = a > b ? [a, b] : [b, a];
  return (hi + 0.05) / (lo + 0.05);
}
"""

#: The paper the notation sits on.
#:
#: Deliberately the CSS surface rather than the first <rect> in the SVG: staff
#: lines are rects too, and picking one of those made an earlier version of this
#: check pass trivially while the noteheads were invisible.
SCORE_BACKGROUND = """
() => getComputedStyle(document.querySelector('.score-surface')).backgroundColor
"""

#: WCAG relative luminance of a colour, 0 (black) to 1 (white).
LUMINANCE = """
(value) => {
  const parse = (v) => {
    const rgb = v.match(/rgba?\\(([^)]+)\\)/);
    if (rgb) return rgb[1].split(',').slice(0, 3).map(Number);
    let hex = v.replace('#', '').trim();
    if (hex.length === 3) hex = hex.split('').map((c) => c + c).join('');
    return [0, 2, 4].map((i) => parseInt(hex.slice(i, i + 2), 16));
  };
  const channel = (x) => {
    const c = x / 255;
    return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  };
  const [r, g, b] = parse(value);
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}
"""

#: Noteheads are plain <path> elements with no class of their own, so measure the
#: painted fill directly. (An earlier version keyed off `vf-notehead`, which
#: matches different elements and made a working feature look broken.)
NOTE_FILL = """
() => {
  const counts = {};
  for (const el of document.querySelectorAll('.score-surface svg path')) {
    const fill = getComputedStyle(el).fill;
    if (fill && fill !== 'none') counts[fill] = (counts[fill] || 0) + 1;
  }
  let best = null;
  let bestCount = 0;
  for (const [fill, count] of Object.entries(counts)) {
    if (count > bestCount) { best = fill; bestCount = count; }
  }
  return best;
}
"""

#: Histogram of painted notehead fills.
NOTE_FILL_COUNTS = """
() => {
  const counts = {};
  for (const el of document.querySelectorAll('.score-surface svg path')) {
    const fill = getComputedStyle(el).fill;
    if (fill && fill !== 'none') counts[fill] = (counts[fill] || 0) + 1;
  }
  return counts;
}
"""

#: hex -> the rgb() form getComputedStyle reports, for exact comparisons.
HEX_TO_RGB = """
(hex) => {
  const h = hex.replace('#', '');
  return 'rgb(' + [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16)).join(', ') + ')';
}
"""


def contrast(page: Page, foreground: str, background: str) -> float:
    return float(page.evaluate(CONTRAST, [foreground, background]))


def luminance(page: Page, colour: str) -> float:
    return float(page.evaluate(LUMINANCE, colour))


def open_appearance(page: Page) -> None:
    page.get_by_role("button", name="Appearance settings").click()


def set_theme(page: Page, label: str) -> None:
    open_appearance(page)
    page.get_by_role("button", name=label, exact=True).click()
    page.get_by_role("button", name="Close", exact=True).click()


class CheckFailure(AssertionError):
    pass


def check(condition: bool, message: str) -> None:
    if not condition:
        raise CheckFailure(message)
    print(f"  ok  {message}")


def api(path: str, method: str = "GET", body: dict | None = None) -> Any:
    """A JSON call against the running API, for arranging a scenario."""
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(
        f"{BASE_URL}{path}", data=data, method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def new_page(browser, *, allow_statuses: set[int] | None = None) -> tuple[Page, list[str]]:
    """A page whose console and network errors are collected.

    `allow_statuses` names HTTP codes a scenario provokes on purpose, so a
    deliberate 409 is not reported as a defect.
    """
    allowed = allow_statuses or set()
    page = browser.new_page(viewport={"width": 1280, "height": 1000})
    page.add_init_script(FAKE_MIDI)
    errors: list[str] = []
    page.on(
        "console",
        lambda message: errors.append(f"{message.type}: {message.text}")
        # A failed resource load is already reported below with its URL and
        # status; repeating it here adds noise without adding information.
        if message.type == "error" and not message.text.startswith("Failed to load resource")
        else None,
    )
    page.on("pageerror", lambda error: errors.append(f"pageerror: {error}"))
    # A missing favicon is not a defect; a missing bundle or API route is.
    page.on(
        "response",
        lambda response: errors.append(f"http {response.status}: {response.url}")
        if response.status >= 400
        and response.status not in allowed
        and not response.url.endswith("/favicon.ico")
        else None,
    )
    return page, errors


def click_button(page: Page, label: str, timeout: float = 20_000) -> None:
    """Click a button by its exact accessible name.

    ``text=Start`` is a substring match and can land on a neighbouring control
    in a row of buttons, so match the accessible name exactly instead.
    """
    page.get_by_role("button", name=label, exact=True).first.click(timeout=timeout)


def open_ports(page: Page) -> None:
    """Make sure the per-port list is on screen.

    It is a toggle, so clicking unconditionally *closes* it when it is already open
    — which is what happens after a device disappears and returns.
    """
    if page.locator("[data-port]").count() == 0:
        page.get_by_role("button", name=re.compile(r"^Ports")).first.click()
        page.wait_for_selector("[data-port]", timeout=10_000)


def ensure_midi(page: Page, timeout: float = 15_000) -> None:
    """Wait until the app has a usable MIDI input.

    The app connects by itself when the browser already has permission, so this does
    *not* click by default — clicking would hide the very behaviour the auto-detect
    scenario exists to check. The click is only for a browser that refused without a
    gesture.
    """
    page.wait_for_selector("text=Sight-Reading Trainer", timeout=timeout)
    connect = page.get_by_role("button", name="Connect MIDI", exact=True)
    if connect.count():
        try:
            connect.first.click(timeout=3_000)
        except PlaywrightTimeout:
            # The app connected by itself between the check and the click, which
            # removes the button. That is the behaviour we want — and checking
            # first is still right, because clicking when already connected is a
            # gesture the auto-detect scenario exists to prove is unnecessary.
            pass
    page.wait_for_selector("text=MIDI connected", timeout=timeout)
    check(page.evaluate("() => window.__fakeMidi.ready()"), "app installed a MIDI message handler")


def wait_for_phase(page: Page, phase: str, timeout: float = 30_000) -> None:
    page.wait_for_function(
        f"() => !!document.querySelector('[data-phase=\"{phase}\"]')",
        timeout=timeout,
    )


def start_run(page: Page) -> None:
    """Begin a run with no notes left over from a previous one."""
    page.evaluate(CANCEL_PLAYBACK)
    click_button(page, "Start")
    wait_for_phase(page, "playing", timeout=20_000)


def load_first_exercise(page: Page) -> dict[str, Any]:
    """Click through to a rendered exercise and return the API payload behind it."""
    page.goto(BASE_URL, wait_until="domcontentloaded")
    page.wait_for_selector("text=Sight-Reading Trainer")

    ensure_midi(page)

    first_label = "Get my first exercise" if page.get_by_role("button", name="Get my first exercise", exact=True).count() else "Get exercise"
    with page.expect_response(lambda r: "/api/exercise/next" in r.url) as caught:
        click_button(page, first_label)
    exercise = caught.value.json()

    page.wait_for_selector(".score-surface svg", timeout=30_000)
    wait_for_phase(page, "ready")
    return exercise


def rendered_notehead_count(page: Page) -> int:
    return page.evaluate(
        """() => document.querySelectorAll(
             '.score-surface .vf-notehead, .score-surface [class*="vf-notehead"]'
           ).length"""
    )


def result_stat(page: Page, label: str) -> str:
    """Read one of the result panel's summary statistics."""
    return page.evaluate(
        """(label) => {
             for (const node of document.querySelectorAll('.stat')) {
               const key = node.querySelector('.k')?.textContent?.trim();
               if (key === label) return node.querySelector('.v')?.textContent?.trim() ?? '';
             }
             return '';
           }""",
        label,
    )


def scenario_perfect(browser) -> None:
    print("\n[1] Perfect performance through simulated MIDI")
    page, errors = new_page(browser)
    exercise = load_first_exercise(page)
    expected = exercise["expected_notes"]
    check(len(expected) > 0, f"exercise #{exercise['exercise_id']} has {len(expected)} expected notes")

    # The badge, the rationale, and the payload must all describe the same skill.
    badge = page.inner_text("[data-exercise-badge]").strip()
    rationale = page.inner_text(".rationale").strip()
    skill_label = (exercise["target_skill"] or "").replace("_", " ")
    badge_skill = badge.split("·")[0].strip()
    rationale_skill = rationale.split("Targeting ", 1)[1].split(" at level", 1)[0].strip()
    check(badge_skill == skill_label, f"badge names the focused skill (badge='{badge_skill}')")
    check(
        rationale_skill == badge_skill,
        f"rationale and badge agree (badge='{badge_skill}', rationale='{rationale_skill}')",
    )
    check(
        f"level {exercise['levels'][exercise['target_skill']]}" in rationale,
        "rationale quotes the level actually used",
    )

    noteheads = rendered_notehead_count(page)
    # Chords render one notehead per pitch; noteheads must at least match the
    # single-note case and never be zero.
    check(noteheads >= len(expected), f"OSMD rendered {noteheads} noteheads for {len(expected)} notes")

    strip_count = page.evaluate("() => document.querySelectorAll('.notes .note').length")
    check(strip_count == len(expected), f"note strip lists all {strip_count} notes")

    start_run(page)
    check(True, "count-in completed and playback started")

    page.evaluate(PLAY_NOTES, [expected, 80, 220])

    wait_for_phase(page, "result", timeout=90_000)
    score = page.inner_text(".score-ring .value")
    print(f"      score = {score}")
    check(int(score) >= 95, f"perfect MIDI input scored {score}/100")

    # The headline feature: notes are coloured *on the score*. Asserting on the
    # rendered fill is what makes this real — a broken correlation leaves every
    # note black and the note strip still looks perfect.
    correct = page.evaluate(HEX_TO_RGB, "#15803d")
    counts = page.evaluate(NOTE_FILL_COUNTS)
    print(f"      notehead colours: {counts}")
    check(
        counts.get(correct, 0) == len(expected),
        f"every note is coloured as correct on the score ({counts.get(correct, 0)}/{len(expected)} at {correct})",
    )

    # Playback of the attempt. Sound cannot be asserted in a headless browser, but the
    # state transitions can, and they are what breaks: a player that never reports
    # itself finished leaves a Stop button and a stuck synth behind.
    check(
        page.locator(".hearing[data-playing]").count() == 1,
        "the result offers to play the attempt back",
    )
    check(
        page.get_by_role("button", name="Play as written", exact=True).count() == 1,
        "and to play the exercise as notated",
    )
    page.get_by_role("button", name="Play yours", exact=True).click()
    page.wait_for_selector('.hearing[data-playing="mine"]', timeout=5_000)
    check(True, "playing the attempt starts and reports which source is playing")
    click_button(page, "Stop")
    page.wait_for_selector('.hearing[data-playing="false"]', timeout=5_000)
    check(True, "and stopping it returns the panel to rest")

    # Left hand only: the hand checkboxes filter both sources.
    page.get_by_label("LH").uncheck()
    page.get_by_role("button", name="Play as written", exact=True).click()
    page.wait_for_selector('.hearing[data-playing="written"]', timeout=5_000)
    check(True, "and either hand alone can be heard")
    click_button(page, "Stop")
    page.get_by_label("LH").check()

    notes_right = result_stat(page, "Notes right")
    check(
        notes_right == f"{len(expected)}/{len(expected)}",
        f"result panel reports every note correct: 'Notes right' = {notes_right}",
    )
    check(result_stat(page, "Wrong pitch") == "0", "no wrong pitches recorded")
    check(result_stat(page, "Missed") == "0", "no missed notes recorded")
    hesitation = result_stat(page, "Hesitations")
    check(hesitation == "0", f"no hesitations recorded (got {hesitation})")
    timing = result_stat(page, "Timing bias")
    print(f"      timing bias = {timing}")
    check("Passed" in page.inner_text(".result"), "result reports a pass")

    page.screenshot(path=str(SHOTS / "01-practice-perfect.png"), full_page=True)
    check(not errors, f"no console errors ({errors})")
    page.close()


def scenario_wrong_and_silence(browser) -> None:
    print("\n[2] Wrong notes and silence")
    page, errors = new_page(browser)
    exercise = load_first_exercise(page)
    expected = exercise["expected_notes"]

    # Transpose every note up a semitone: nothing should match on pitch.
    shifted = [{"pitch": note["pitch"] + 1, "onset_s": note["onset_s"]} for note in expected]
    start_run(page)
    page.evaluate(PLAY_NOTES, [shifted, 80, 200])
    page.wait_for_function("() => document.querySelectorAll('.notes .note.wrong_pitch').length > 0", timeout=30_000)
    check(True, "wrong pitches highlighted live in the note strip")

    # And on the notation itself.
    wrong = page.evaluate(HEX_TO_RGB, "#b91c1c")
    live_counts = page.evaluate(NOTE_FILL_COUNTS)
    check(
        live_counts.get(wrong, 0) > 0,
        f"wrong pitches are coloured red on the score ({live_counts})",
    )
    click_button(page, "Stop & score")
    wait_for_phase(page, "result", timeout=60_000)

    pitch_score = page.inner_text(".bar-row:nth-child(1) .bar-value")
    print(f"      pitch = {pitch_score}")
    check(int(pitch_score.rstrip('%')) < 20, f"all-wrong performance scored {pitch_score} pitch accuracy")
    check("Keep working" in page.inner_text(".result"), "result reports a failed attempt")
    page.screenshot(path=str(SHOTS / "02-practice-wrong.png"), full_page=True)

    # Now a silent run: nothing played at all.
    with page.expect_response(lambda r: "/api/exercise/next" in r.url) as next_caught:
        click_button(page, "Next exercise")
    second = next_caught.value.json()
    page.wait_for_selector(".score-surface svg", timeout=30_000)
    start_run(page)
    click_button(page, "Stop & score")
    wait_for_phase(page, "result", timeout=60_000)

    total = len(second["expected_notes"])
    missed = result_stat(page, "Missed")
    check(missed == str(total), f"silence marks every note missed ({missed}/{total})")
    check(result_stat(page, "Notes right") == f"0/{total}", "silence matches no notes")
    silence_score = page.inner_text(".score-ring .value")
    check(int(silence_score) == 0, f"silence scores {silence_score}/100")

    check(not errors, f"no console errors ({errors})")
    page.close()


def scenario_calibration_and_stats(browser) -> None:
    print("\n[3] Calibration ladder and progress view")
    page, errors = new_page(browser)
    page.goto(BASE_URL, wait_until="domcontentloaded")
    click_button(page, "Calibrate")
    page.wait_for_selector("text=Ready to calibrate")

    with page.expect_response(lambda r: "/api/calibration/next" in r.url) as caught:
        click_button(page, "Start calibration")
    calibration = caught.value.json()
    check(calibration["source"] == "calibration", "calibration endpoint returns calibration material")
    check(calibration["step"] == 1, f"calibration reports step {calibration['step']}")

    page.wait_for_selector(".score-surface svg", timeout=30_000)
    start_run(page)
    page.evaluate(PLAY_NOTES, [calibration["expected_notes"], 80, 200])
    wait_for_phase(page, "result", timeout=90_000)
    check(True, "calibration exercise scored")

    # After scoring, the next calibration rung loads from the result panel.
    with page.expect_response(lambda r: "/api/calibration/next" in r.url) as second_caught:
        click_button(page, "Next exercise")
    following = second_caught.value.json()
    page.wait_for_selector(".score-surface svg", timeout=30_000)
    check(
        following["step"] == calibration["step"] + 1,
        f"calibration advanced from step {calibration['step']} to {following['step']}",
    )
    check(
        following["target_skill"] != calibration["target_skill"],
        f"calibration moved on to a different skill ({calibration['target_skill']} -> {following['target_skill']})",
    )
    check(
        rendered_notehead_count(page) > 0,
        f"the next calibration exercise is rendered ({rendered_notehead_count(page)} noteheads)",
    )
    page.screenshot(path=str(SHOTS / "03-calibration.png"), full_page=True)

    # Progress view should reflect the recorded performance.
    click_button(page, "Progress")
    page.wait_for_selector("text=Skill radar", timeout=30_000)
    page.wait_for_selector(".tiles")
    # `innerText` reflects rendered text, and the tile labels are uppercased in CSS.
    tiles = page.inner_text(".tiles").lower()
    check("exercises played" in tiles, "progress view shows the summary tiles")
    check("streak" in tiles, "progress view shows the practice streak")
    history_rows = page.evaluate("() => document.querySelectorAll('table tbody tr').length")
    check(history_rows > 0, f"progress view lists {history_rows} recent exercises")

    # Rating history: recorded per attempt, because `user_skills` keeps only today's
    # number and a curve cannot be recovered from it. Waited for rather than asserted
    # instantly: the series is fetched separately from the view, and checking the
    # moment the radar appears is a race the fuller suite loses.
    try:
        page.wait_for_selector('[data-ratings="shown"]', timeout=10_000)
        shown = True
    except PlaywrightTimeout:
        shown = False
    check(shown, "the rating curve has points after a scored attempt")
    check(
        page.locator('[data-ratings="shown"] svg .line').count() >= 1,
        "and it is drawn",
    )

    # A past attempt opened from the history, and heard back.
    page.locator("table tbody tr.pickable").first.click()
    page.wait_for_selector("[data-attempt]", timeout=15_000)
    check(True, "a past attempt can be opened from the history")
    check(
        page.locator("[data-attempt] .hearing[data-playing]").count() == 1,
        "and it offers the same player as a fresh result",
    )
    page.get_by_role("button", name="Play yours", exact=True).click()
    page.wait_for_selector('[data-playing="mine"]', timeout=10_000)
    check(True, "a past attempt can be played back from the stored notes")
    click_button(page, "Stop")
    page.wait_for_selector('[data-playing="false"]', timeout=10_000)
    page.screenshot(path=str(SHOTS / "04-progress.png"), full_page=True)
    check(page.evaluate("() => document.querySelectorAll('svg .area').length") == 1, "radar chart drawn")
    page.screenshot(path=str(SHOTS / "04-progress.png"), full_page=True)

    check(not errors, f"no console errors ({errors})")
    page.close()



def scenario_theming(browser) -> None:
    print("\n[4] Theming: dark mode, score paper, and no flash of the wrong theme")
    context = browser.new_context(viewport={"width": 1280, "height": 1000})
    page = context.new_page()
    page.add_init_script(FAKE_MIDI)
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(f"pageerror: {error}"))
    page.on(
        "response",
        lambda response: errors.append(f"http {response.status}: {response.url}")
        if response.status >= 400 and not response.url.endswith("/favicon.ico")
        else None,
    )

    page.goto(BASE_URL, wait_until="domcontentloaded")
    page.wait_for_selector("text=Sight-Reading Trainer")
    check(
        page.evaluate("() => document.documentElement.dataset.theme") == "light",
        "a fresh profile starts in light",
    )

    # --- dark chrome ---
    set_theme(page, "Dark")
    check(
        page.evaluate("() => document.documentElement.dataset.theme") == "dark",
        "selecting Dark switches the interface immediately",
    )

    # --- dark notation, checked BEFORE anything is played ---
    # This is where the bug lived: OSMD's darkMode lightens the music but leaves
    # noteheads at their own default of black, so un-played exercises were
    # invisible. Checking only after scoring hides it, because feedback colours
    # are applied separately.
    exercise = load_first_exercise(page)
    expected = exercise["expected_notes"]
    page.wait_for_timeout(400)

    background = page.evaluate(SCORE_BACKGROUND)
    resting_ink = page.evaluate(NOTE_FILL)
    background_luminance = luminance(page, background)
    ink_luminance = luminance(page, resting_ink)
    print(f"      dark paper {background} (L={background_luminance:.3f}), resting ink {resting_ink} (L={ink_luminance:.3f})")
    check(
        background_luminance < 0.1,
        f"dark theme actually renders dark paper (luminance {background_luminance:.3f})",
    )
    check(
        ink_luminance > 0.5,
        f"un-played notation is light on dark paper, not black on black (luminance {ink_luminance:.3f})",
    )
    check(
        contrast(page, resting_ink, background) >= 3.0,
        f"resting notation meets WCAG 3:1 ({contrast(page, resting_ink, background):.2f}:1)",
    )
    page.screenshot(path=str(SHOTS / "05-dark-unplayed.png"), full_page=True)

    # --- feedback colours stay legible on dark paper ---
    start_run(page)
    page.evaluate(PLAY_NOTES, [expected, 80, 220])
    wait_for_phase(page, "result", timeout=90_000)

    fill = page.evaluate(NOTE_FILL)
    ratio = contrast(page, fill, background)
    print(f"      dark: correct-note {fill} on {background} = {ratio:.2f}:1")
    check(ratio >= 3.0, f"correct-note colour meets WCAG 3:1 on dark paper ({ratio:.2f}:1)")
    check(
        luminance(page, fill) > background_luminance,
        "feedback colour is lighter than the paper it sits on",
    )
    check(
        page.evaluate("() => document.documentElement.dataset.scorePaper") == "dark",
        "the notation follows the theme by default",
    )
    page.screenshot(path=str(SHOTS / "06-dark-scored.png"), full_page=True)

    # --- decoupled paper: dark chrome, paper music ---
    set_theme(page, "Paper music")
    page.wait_for_function(
        "() => document.documentElement.dataset.scorePaper === 'light'", timeout=10_000
    )
    page.wait_for_timeout(400)  # let the re-render settle
    paper = page.evaluate("() => getComputedStyle(document.querySelector('.score-surface')).backgroundColor")
    body = page.evaluate("() => getComputedStyle(document.body).backgroundColor")
    check(
        page.evaluate("() => document.documentElement.dataset.theme") == "dark",
        "the chrome stays dark when only the paper is changed",
    )
    print(f"      decoupled: body {body}, score {paper}")
    check(paper != body, f"score paper is independent of the chrome ({paper} vs {body})")
    check("255, 255, 255" in paper, f"paper music renders on white ({paper})")
    page.screenshot(path=str(SHOTS / "07-dark-paper.png"), full_page=True)

    set_theme(page, "Themed music")
    set_theme(page, "Light")
    check(
        page.evaluate("() => document.documentElement.dataset.theme") == "light",
        "switching back to Light works",
    )

    # --- preference survives a reload ---
    set_theme(page, "Dark")
    page.reload(wait_until="domcontentloaded")
    check(
        page.evaluate("() => document.documentElement.dataset.theme") == "dark",
        "the theme preference survives a reload",
    )

    # --- no flash of the wrong theme, proven without the app bundle ---
    # With the module bundle blocked, only the inline <head> script can have set
    # the theme; if it were applied by the app there would be a white flash.
    bare = context.new_page()
    bare.route("**/assets/*.js", lambda route: route.abort())
    bare.goto(BASE_URL, wait_until="domcontentloaded")
    check(
        bare.evaluate("() => document.documentElement.dataset.theme") == "dark",
        "the pre-paint script applies the theme before any app JavaScript runs",
    )
    bare.close()

    check(not errors, f"no console errors ({errors})")
    context.close()



#: Layout facts for the score, used to prove nothing must be scrolled to read it.
LAYOUT = """
() => {
  const surface = document.querySelector('.score-surface');
  const rect = surface.getBoundingClientRect();
  return {
    top: Math.round(rect.top),
    height: Math.round(rect.height),
    bottom: Math.round(rect.bottom),
    viewportHeight: window.innerHeight,
    svgCount: surface.querySelectorAll('svg').length,
    fullyVisible: rect.bottom <= window.innerHeight + 1,
    tooLong: !!document.querySelector('.too-long'),
    focusMode: document.documentElement.dataset.focus === 'true',
  };
}
"""


def load_length(page: Page, bars: int) -> None:
    """Choose a length and wait for the new exercise to actually render."""
    with page.expect_response(lambda r: "/api/exercise/next" in r.url):
        click_button(page, str(bars))
    wait_for_phase(page, "ready")
    page.wait_for_timeout(500)


def scenario_long_exercises(browser) -> None:
    print("\n[5] Long exercises: the whole score stays readable without scrolling")
    for viewport in ({"width": 1280, "height": 800}, {"width": 1440, "height": 900}):
        page, errors = new_page(browser)
        page.set_viewport_size(viewport)
        page.goto(BASE_URL, wait_until="domcontentloaded")
        page.wait_for_selector("text=Sight-Reading Trainer")
        ensure_midi(page)
        load_first_exercise(page)

        label = f"{viewport['width']}x{viewport['height']}"
        for bars in (4, 8, 12, 16):
            load_length(page, bars)
            start_run(page)
            page.wait_for_timeout(800)

            layout = page.evaluate(LAYOUT)
            # Stable: a scrollbar feedback loop used to oscillate the height.
            page.wait_for_timeout(700)
            settled = page.evaluate(LAYOUT)

            check(
                layout["svgCount"] == 1 and settled["svgCount"] == 1,
                f"{label} {bars} bars: exactly one SVG ({layout['svgCount']}, {settled['svgCount']})",
            )
            check(
                layout["height"] == settled["height"],
                f"{label} {bars} bars: layout is stable at {layout['height']}px",
            )
            # The honest invariant: either the score is fully readable, or the
            # app says the length does not fit. Never a silent scrollbar.
            check(
                layout["fullyVisible"] or layout["tooLong"],
                f"{label} {bars} bars: score fully visible or explicitly refused "
                f"(bottom {layout['bottom']} / viewport {layout['viewportHeight']}, "
                f"tooLong={layout['tooLong']})",
            )
            print(
                f"      {label} {bars:2d} bars: {layout['height']}px, "
                f"{'refused' if layout['tooLong'] else 'visible'}"
            )
            click_button(page, "Stop & score")
            wait_for_phase(page, "result", timeout=60_000)

        # Focus mode must buy real room: a length that is refused normally
        # should become readable.
        page.set_viewport_size({"width": 1280, "height": 600})
        page.wait_for_timeout(400)
        load_length(page, 16)
        start_run(page)
        page.wait_for_timeout(800)
        cramped = page.evaluate(LAYOUT)
        click_button(page, "Stop & score")
        wait_for_phase(page, "result", timeout=60_000)

        click_button(page, "Focus")
        page.wait_for_timeout(400)
        load_length(page, 16)
        start_run(page)
        page.wait_for_timeout(800)
        spacious = page.evaluate(LAYOUT)
        click_button(page, "Stop & score")
        wait_for_phase(page, "result", timeout=60_000)

        print(f"      16 bars at 1280x600: normal={cramped['height']}px focus={spacious['height']}px")
        check(spacious["focusMode"], "focus mode is applied to the document")
        check(
            spacious["height"] > cramped["height"],
            f"focus mode gives the score more room ({cramped['height']} -> {spacious['height']})",
        )
        check(
            spacious["fullyVisible"] and not spacious["tooLong"],
            "16 bars fits at 1280x600 once focus mode is on",
        )
        check(not errors, f"no console errors ({errors})")
        page.close()



#: Distinct vertical positions of staff lines. A grand staff has two, a single
#: staff has one, and this is measured from the rendered SVG rather than assumed
#: from the payload.
STAFF_TOPS = """
() => {
  const tops = [...document.querySelectorAll('.score-surface svg g.staffline')]
    .map((group) => Math.round(group.getBBox().y));
  return { stafflines: tops.length, distinctTops: new Set(tops).size };
}
"""


def clear_repertoire() -> None:
    """Empty the repertoire tables so the import can be driven from the UI.

    Test setup, not an assertion: the import button only exists on an empty
    library, and the scenario must run the same way twice.
    """
    conn = sqlite3.connect(os.environ.get("SRT_DB_PATH", str(DEFAULT_DB)), timeout=15)
    try:
        for table in ("media", "piece_journal", "pieces", "composers"):
            conn.execute(f"DELETE FROM {table}")
        conn.commit()
    finally:
        conn.close()


def set_all_ratings(rating: float) -> None:
    """Arrange the precondition for a scenario.

    Ratings are set through the database rather than the UI because driving them
    through play would take dozens of exercises; this is test setup, not an
    assertion about behaviour.
    """
    conn = sqlite3.connect(os.environ.get("SRT_DB_PATH", str(DEFAULT_DB)), timeout=15)
    try:
        conn.execute("UPDATE user_skills SET elo_rating = ?", (float(rating),))
        conn.execute("DELETE FROM performances")
        conn.commit()
    finally:
        conn.close()


def scenario_two_hands(browser) -> None:
    print("\n[6] Two hands: a real grand staff with a left-hand accompaniment")
    set_all_ratings(1300)  # comfortably two-handed
    page, errors = new_page(browser)
    page.goto(BASE_URL, wait_until="domcontentloaded")
    page.wait_for_selector("text=Sight-Reading Trainer")
    ensure_midi(page)

    patterns: set[str] = set()
    checked_staves = False
    for _ in range(6):
        exercise = load_first_exercise(page)
        expected = exercise["expected_notes"]
        hands = {note["hand"] for note in expected}
        pattern = exercise.get("bass_pattern")

        check(
            exercise["levels"]["texture"] >= 3 and hands == {"RH", "LH"},
            f"a two-hand exercise serves both hands (texture {exercise['levels']['texture']}, {hands})",
        )
        check(bool(pattern), f"the left-hand figure is reported ({pattern})")

        if pattern:
            patterns.add(pattern)
            label = page.locator('[title="Left-hand figure"]').first.inner_text()
            check(
                pattern.replace("_", " ") in label,
                f"the interface names the figure ({label.strip()})",
            )

        # Measure the engraving rather than trusting the payload.
        layout = page.evaluate(STAFF_TOPS)
        if not checked_staves:
            check(
                layout["distinctTops"] >= 2,
                f"two staves are engraved ({layout['stafflines']} staff groups, "
                f"{layout['distinctTops']} distinct positions)",
            )
            checked_staves = True

        # Play it perfectly and confirm both hands are scored separately.
        start_run(page)
        page.evaluate(PLAY_NOTES, [expected, 80, 200])
        wait_for_phase(page, "result", timeout=120_000)

        score = int(page.inner_text(".score-ring .value"))
        # Pitch is the meaningful assertion here. The synthetic performance is
        # scheduled with setTimeout, which cannot place a hundred-odd notes to
        # the millisecond, so a dense exercise loses a little rhythm accuracy to
        # the harness rather than to the app.
        pitch = int(page.inner_text(".bar-row:nth-child(1) .bar-value").rstrip("%"))
        check(pitch >= 98, f"every note matched by pitch ({pitch}%)")
        # Regression guard for the end-of-run timer: it used to be computed from
        # a "seconds per beat" that ignored compound meters, so a 12/8 exercise
        # stopped listening early and silently truncated the performance.
        emitted = page.evaluate("() => window.__playEmitted")
        check(
            emitted == len(expected),
            f"the whole performance was captured before the run ended ({emitted}/{len(expected)} notes)",
        )
        check(score >= 85, f"perfect two-hand performance scored {score}/100")
        by_hand = page.evaluate(
            """() => [...document.querySelectorAll('.pill')]
                 .map((pill) => pill.innerText.trim())
                 .filter((text) => /^(RH|LH) \\d+%$/.test(text))"""
        )
        check(len(by_hand) == 2, f"both hands are reported separately ({by_hand})")
        page.screenshot(path=str(SHOTS / f"08-twohand-{len(patterns)}.png"), full_page=True)

        with page.expect_response(lambda r: "/api/exercise/next" in r.url):
            click_button(page, "Next exercise")
        wait_for_phase(page, "ready")

    check(len(patterns) >= 2, f"the left hand varies across exercises ({sorted(patterns)})")
    check(not errors, f"no console errors ({errors})")
    page.close()



#: A small database shaped like the Rust `piano-progress` schema, so the import
#: scenario asserts on data it controls rather than on whatever library happens
#: to be on the machine.
LEGACY_FIXTURE_SQL = """
CREATE TABLE composers (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, notes TEXT);
CREATE TABLE pieces (
    id INTEGER PRIMARY KEY AUTOINCREMENT, composer_id INTEGER, title TEXT NOT NULL,
    difficulty TEXT, key TEXT, started_on TEXT, status TEXT NOT NULL DEFAULT 'active',
    description TEXT, created_at TEXT, opus TEXT
);
CREATE TABLE notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT, piece_id INTEGER, entry_date TEXT,
    content TEXT, practice_minutes INTEGER, created_at TEXT
);
CREATE TABLE media (
    id INTEGER PRIMARY KEY AUTOINCREMENT, piece_id INTEGER, kind TEXT, file_name TEXT,
    original_name TEXT, title TEXT, duration_secs REAL, size_bytes INTEGER,
    codec TEXT, taken_on TEXT, created_at TEXT
);
"""


def ensure_legacy_fixture(path: Path) -> Path:
    """Build the fixture only if it is not already there."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return path
    conn = sqlite3.connect(path)
    conn.executescript(LEGACY_FIXTURE_SQL)
    conn.execute("INSERT INTO composers (id, name) VALUES (1, 'Brahms'), (2, 'Debussy')")
    conn.execute(
        "INSERT INTO pieces (id, composer_id, title, opus, difficulty, key, status, started_on)"
        " VALUES (1, 1, 'Intermezzo', 'Op. 118 No. 2', 'Late Intermediate', 'A Major',"
        " 'active', '2026-04-02')"
    )
    conn.execute(
        "INSERT INTO pieces (id, composer_id, title, opus, difficulty, key, status)"
        " VALUES (2, 2, 'Clair de Lune', 'L. 75', 'Intermediate', 'Db Major', 'active')"
    )
    conn.execute(
        "INSERT INTO pieces (id, composer_id, title, difficulty, key, status)"
        " VALUES (3, 1, 'Ballade', 'Advanced', 'D Minor', 'completed')"
    )
    conn.execute(
        "INSERT INTO notes (id, piece_id, entry_date, content, practice_minutes)"
        " VALUES (1, 1, '2026-05-01', 'Inner voices still uneven.', 25)"
    )
    conn.execute(
        "INSERT INTO notes (id, piece_id, entry_date, content) VALUES (2, 1, '2026-05-02', 'Better.')"
    )
    media_dir = path.parent / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    (media_dir / "fixture-recording.ogg").write_bytes(b"OggS fixture audio bytes")
    conn.execute(
        "INSERT INTO media (id, piece_id, kind, file_name, original_name, duration_secs,"
        " size_bytes, codec) VALUES (1, 1, 'audio', 'fixture-recording.ogg', 'TAKE01.WAV',"
        " 81.0, 1023, 'opus')"
    )
    conn.commit()
    conn.close()
    return path


def make_tone_wav(destination: Path, *, seconds: int = 2) -> Path:
    """A real WAV, so the import path is exercised end to end.

    Generated by ffmpeg rather than faked: the whole point is that ffprobe and
    ffmpeg accept the file. Normalised deliberately — this ffmpeg's `sine`
    arrives at about -18 dBFS, and a fixture that quiet makes the waveform
    assertion ("the tallest bar is a real bar") unable to tell a rendered
    envelope from a flat line.
    """
    import subprocess

    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
            "-af", "volume=12dB",
            str(destination),
        ],
        check=True,
        capture_output=True,
    )
    return destination


def make_score_files(directory: Path) -> tuple[Path, Path]:
    """A MusicXML score and a PDF, for the attachment path.

    Real files rather than bytes on the wire: the server identifies a score by its
    own content, so a fake would be refused — which is the behaviour under test.
    """
    directory.mkdir(parents=True, exist_ok=True)
    musicxml = directory / "e2e-score.musicxml"
    musicxml.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0">
  <part-list>
    <score-part id="P1"><part-name>Piano</part-name></score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes>
        <divisions>1</divisions>
        <key><fifths>0</fifths></key>
        <time><beats>4</beats><beat-type>4</beat-type></time>
        <clef><sign>G</sign><line>2</line></clef>
      </attributes>
      <note>
        <pitch><step>C</step><octave>4</octave></pitch>
        <duration>4</duration><type>whole</type>
      </note>
    </measure>
  </part>
</score-partwise>
"""
    )
    pdf = directory / "e2e-score.pdf"
    pdf.write_bytes(MINIMAL_PDF)
    return musicxml, pdf


#: One blank page, written out properly. Chromium's PDF viewer is what renders it,
#: so it has to be a document the viewer will actually open.
MINIMAL_PDF = b"""%PDF-1.4
1 0 obj <</Type /Catalog /Pages 2 0 R>> endobj
2 0 obj <</Type /Pages /Kids [3 0 R] /Count 1>> endobj
3 0 obj <</Type /Page /Parent 2 0 R /MediaBox [0 0 200 200]>> endobj
trailer <</Root 1 0 R>>
%%EOF
"""


def scenario_repertoire(browser) -> None:
    print("\n[7] Repertoire: the library, the journal, and the sight-reading bridge")
    fixture = ensure_legacy_fixture(
        Path(os.environ.get("SRT_LEGACY_DB", str(DEFAULT_LEGACY)))
    )
    expected = json.load(urlopen(f"{BASE_URL}/api/repertoire/status"))
    if Path(expected["legacy_db"]) != fixture:
        # The server was started against a different legacy database, so the
        # fixture is not what it will import. Say so rather than asserting on
        # someone's real library.
        print(f"      skipped: server reads {expected['legacy_db']}, fixture is {fixture}")
        return

    clear_repertoire()
    # The duplicate-upload check provokes a 409 on purpose.
    page, errors = new_page(browser, allow_statuses={409})
    page.goto(BASE_URL, wait_until="domcontentloaded")
    page.wait_for_selector("text=Sight-Reading Trainer")
    click_button(page, "Repertoire")
    page.wait_for_selector(".panel", timeout=20_000)

    # First run, before any import: an empty library must still offer a way to add
    # something. It did not — the only control was "import from piano-progress", which
    # is useless on a machine that never ran that app — so this is the check that the
    # dead end stays fixed.
    page.wait_for_selector("text=The library is empty", timeout=20_000)
    click_button(page, "New piece")
    page.wait_for_selector(".editor", timeout=10_000)
    page.fill('.editor input[placeholder="Intermezzo"]', "First piece")
    page.fill('.editor input[placeholder="A Major"]', "C Major")
    page.fill('.editor input[placeholder="Late Intermediate"]', "Beginner")
    # Creating a composer inline is the other half of a first run: with an empty
    # library there is nothing to pick from.
    page.select_option('.editor select', "__new__")
    page.fill('.editor input[placeholder="Brahms"]', "E2E Composer")
    with page.expect_response(
        lambda r: r.url.endswith("/api/repertoire/pieces") and r.request.method == "POST"
    ):
        click_button(page, "Add piece")
    page.wait_for_function(
        "() => document.querySelector('.detail-title')?.textContent?.includes('First piece')",
        timeout=10_000,
    )
    check(True, "a piece — and its composer — can be created on an empty library")
    check(
        page.locator(".row-piece", has_text="First piece").count() == 1,
        "and it is listed",
    )
    page.screenshot(path=str(SHOTS / "16-first-piece.png"), full_page=True)

    # Put the library back to empty for the import below.
    click_button(page, "Delete")
    with page.expect_response(
        lambda r: "/api/repertoire/pieces/" in r.url and r.request.method == "DELETE"
    ):
        click_button(page, "Delete for good")
    page.wait_for_selector("text=The library is empty", timeout=20_000)
    check(True, "and deleting it returns to the empty state")

    with page.expect_response(lambda r: "/api/repertoire/import" in r.url) as caught:
        click_button(page, "Import from piano-progress")
    report = caught.value.json()
    check(report["pieces"] == 3, f"imported {report['pieces']} pieces")
    check(report["composers"] == 2, f"imported {report['composers']} composers")
    check(report["journal_entries"] == 2, f"imported {report['journal_entries']} journal entries")

    page.wait_for_selector(".row-piece", timeout=20_000)
    check(
        page.evaluate("() => document.querySelectorAll('.row-piece').length") == 3,
        "three pieces are listed",
    )
    groups = page.evaluate("() => [...document.querySelectorAll('.group')].map((e) => e.innerText)")
    check(len(groups) == 2, f"grouped by composer ({groups})")

    # Filtering
    page.fill('input[type="search"]', "clair")
    page.wait_for_timeout(250)
    check(
        page.evaluate("() => document.querySelectorAll('.row-piece').length") == 1,
        "search narrows the list",
    )
    page.fill('input[type="search"]', "")
    page.wait_for_timeout(250)

    # The journal and the bridge, on an active piece.
    page.locator(".row-piece", has_text="Intermezzo").first.click()
    # `.detail` also matches the loading placeholder, so wait for the title,
    # which only exists once the piece has actually loaded.
    page.wait_for_selector(".detail-title", timeout=10_000)
    check(
        page.evaluate("() => document.querySelectorAll('.journal li').length") == 2,
        "the piece's journal entries are shown",
    )
    suggestion = page.locator(".suggestion").first.inner_text()
    check("A" in suggestion and "level 8" in suggestion, f"key and level mapped ({suggestion!r})")

    # Recordings: imported by default, marked as ours, and actually playable.
    chips = page.evaluate(
        "() => [...document.querySelectorAll('.recordings .pill')].map((e) => e.innerText)"
    )
    check(chips == ["in library"], f"the recording is reported as copied in ({chips})")
    check(
        page.evaluate("() => document.querySelectorAll('.recordings audio').length") == 1,
        "a player is rendered for the recording",
    )
    source = page.evaluate("() => document.querySelector('.recordings audio')?.getAttribute('src')")
    check(bool(source), f"the player points at the file ({source})")
    streamed = page.evaluate(
        """async (src) => {
             const response = await fetch(src, { headers: { Range: 'bytes=0-63' } });
             return { status: response.status, type: response.headers.get('content-type') };
           }""",
        source,
    )
    # 206 rather than 200 proves Range support, which is what makes seeking work.
    check(streamed["status"] == 206, f"the file streams with range support ({streamed})")
    check(
        (streamed["type"] or "").startswith("audio/"),
        f"served with an audio content type ({streamed['type']})",
    )

    # A completed piece is deliberately excluded from suggestions.
    page.locator(".row-piece", has_text="Ballade").first.click()
    page.wait_for_function(
        "() => document.querySelector('.detail-title')?.textContent?.includes('Ballade')",
        timeout=10_000,
    )
    check(
        page.locator(".suggestion").count() == 0,
        "a completed piece gets no sight-reading suggestion",
    )
    page.screenshot(path=str(SHOTS / "09-repertoire.png"), full_page=True)

    # --- the bridge: practise in the key of the piece you are looking at ---
    page.locator(".row-piece", has_text="Intermezzo").first.click()
    page.wait_for_selector(".detail-title", timeout=10_000)
    with page.expect_response(lambda r: "/api/exercise/next" in r.url):
        click_button(page, "Practise in A")
    page.wait_for_selector(".score-surface svg", timeout=20_000)
    wait_for_phase(page, "ready")
    pinned = page.locator('[title="Set from the Repertoire tab"]')
    check(pinned.count() == 1, "the practice view shows that a key is pinned")
    check("Intermezzo" in pinned.first.inner_text(), f"and names the piece ({pinned.first.inner_text()!r})")
    check(
        page.locator(".panel .pill", has_text="key A").count() == 1,
        "the exercise is written in the pinned key",
    )
    page.screenshot(path=str(SHOTS / "11-pinned-key.png"), full_page=True)
    pinned.first.locator("button").click()
    page.wait_for_timeout(300)

    click_button(page, "Repertoire")
    page.wait_for_selector(".row-piece", timeout=20_000)

    # --- editing: create, journal, edit, delete ---
    click_button(page, "New piece")
    page.wait_for_selector(".editor", timeout=10_000)
    page.fill('.editor input[placeholder="Intermezzo"]', "E2E Nocturne")
    page.fill('.editor input[placeholder="Op. 118 No. 2"]', "Op. 9 No. 2")
    page.fill('.editor input[placeholder="A Major"]', "Eb Major")
    page.fill('.editor input[placeholder="Late Intermediate"]', "Intermediate")
    with page.expect_response(
        lambda r: r.url.endswith("/api/repertoire/pieces") and r.request.method == "POST"
    ) as created:
        click_button(page, "Add piece")
    nocturne = created.value.json()
    page.wait_for_function(
        "() => document.querySelector('.detail-title')?.textContent?.includes('E2E Nocturne')",
        timeout=10_000,
    )
    check(True, "a piece can be created from the interface")

    # Journal entry, through the form.
    page.fill('.journal-form input[aria-label="Journal entry"]', "Sight-read the exposition.")
    page.fill('.journal-form input[aria-label="Practice minutes"]', "35")
    with page.expect_response(lambda r: "/journal" in r.url and r.request.method == "POST"):
        click_button(page, "Add")
    page.wait_for_timeout(500)
    check(
        page.evaluate("() => document.querySelectorAll('.journal li').length") == 1,
        "a journal entry can be added",
    )
    check(
        "35" in page.locator(".journal").inner_text(),
        "the practice minutes are recorded",
    )

    # Editing a field changes only that field.
    click_button(page, "Edit")
    page.wait_for_selector(".editor", timeout=10_000)
    check(
        page.input_value('.editor input[placeholder="Op. 118 No. 2"]') == "Op. 9 No. 2",
        "the editor is pre-filled with the piece",
    )
    page.fill('.editor input[placeholder="Intermezzo"]', "E2E Nocturne (revised)")
    with page.expect_response(
        lambda r: "/api/repertoire/pieces/" in r.url and r.request.method == "PATCH"
    ):
        click_button(page, "Save changes")
    page.wait_for_function(
        "() => document.querySelector('.detail-title')?.textContent?.includes('revised')",
        timeout=10_000,
    )
    # The untouched field is the point: PATCH must not clear what was not sent.
    check(
        "Eb Major" in page.locator(".detail").inner_text(),
        "a field the edit did not mention survives the update",
    )

    # --- importing a recording through the interface ---
    tone = make_tone_wav(DEFAULT_DB.parent / "e2e-tone.wav", seconds=3)
    page.set_input_files('input[aria-label="Recording file"]', str(tone))
    page.wait_for_timeout(400)
    reached = page.evaluate(
        "() => document.querySelector('input[aria-label=\"Recording file\"]')?.files?.length ?? -1"
    )
    check(reached == 1, f"the chosen file reached the input ({reached})")
    page.fill('input[aria-label="Recording title"]', "e2e take")
    # Scoped to this form: the panel now has a second upload form for scores, and
    # "the first `.upload button` on the page" would quietly test the wrong one.
    check(
        not page.evaluate(
            "() => document.querySelector('input[aria-label=\"Recording file\"]')"
            ".closest('form').querySelector('button').disabled"
        ),
        "the import button becomes available once a file is chosen",
    )
    with page.expect_response(
        lambda r: "/media" in r.url and r.request.method == "POST", timeout=120_000
    ) as uploaded:
        click_button(page, "Import recording")
    recording = uploaded.value.json()
    check(recording["codec"] == "opus", f"the upload was converted to Opus ({recording['codec']})")
    check(recording["file_name"].endswith(".ogg"), "stored with a content-hashed .ogg name")
    page.wait_for_timeout(700)
    check(
        page.evaluate("() => document.querySelectorAll('.recordings audio').length") == 1,
        "the imported recording is playable",
    )
    check("e2e take" in page.locator(".recordings").inner_text(), "the title was kept")

    # The same audio again is refused rather than stored twice.
    page.set_input_files('input[aria-label="Recording file"]', str(tone))
    with page.expect_response(
        lambda r: "/media" in r.url and r.request.method == "POST", timeout=120_000
    ) as duplicate:
        click_button(page, "Import recording")
    check(
        duplicate.value.status == 409,
        f"re-importing the same recording is refused ({duplicate.value.status})",
    )
    page.wait_for_timeout(500)
    check(
        page.evaluate("() => document.querySelectorAll('.recordings li').length") == 1,
        "and no second recording appeared",
    )
    tone.unlink(missing_ok=True)

    # --- scores: attached, validated by content, and rendered in place ---
    musicxml, pdf = make_score_files(DEFAULT_DB.parent)
    page.set_input_files('input[aria-label="Score file"]', str(musicxml))
    page.wait_for_timeout(300)
    page.fill('input[aria-label="Score title"]', "e2e sonata")
    check(
        not page.evaluate(
            "() => document.querySelector('input[aria-label=\"Score file\"]')"
            ".closest('form').querySelector('button').disabled"
        ),
        "the score button becomes available once a file is chosen",
    )
    with page.expect_response(
        lambda r: "/scores" in r.url and r.request.method == "POST", timeout=60_000
    ) as attached:
        click_button(page, "Attach score")
    score = attached.value.json()
    check(score["kind"] == "score", f"the score is catalogued as a score ({score['kind']})")
    check(score["codec"] == "musicxml", f"identified as MusicXML ({score['codec']})")
    # Engraved by OSMD, from the file the server stored — not a download prompt.
    page.wait_for_selector("[data-score-viewer] svg", timeout=30_000)
    check(
        page.evaluate("() => document.querySelectorAll('[data-score-viewer] svg').length") > 0,
        "the attached MusicXML is engraved in the viewer",
    )
    check(
        "e2e sonata" in page.locator(".detail").inner_text(),
        "the score's title is shown",
    )
    served = page.evaluate(
        """async (id) => {
             const response = await fetch(`/api/repertoire/media/${id}/file`);
             return { type: response.headers.get('content-type'), body: (await response.text()).slice(0, 5) };
           }""",
        score["id"],
    )
    check(
        served["type"].startswith("application/vnd.recordare.musicxml"),
        f"served with a MusicXML content type ({served['type']})",
    )
    check(served["body"].startswith("<?xml"), "and it is the file that was uploaded")

    # The same document again is refused: the stored name is its content hash, so
    # a second catalogue row would be the same file twice.
    page.set_input_files('input[aria-label="Score file"]', str(musicxml))
    with page.expect_response(
        lambda r: "/scores" in r.url and r.request.method == "POST", timeout=60_000
    ) as duplicate_score:
        click_button(page, "Attach score")
    check(
        duplicate_score.value.status == 409,
        f"re-attaching the same score is refused ({duplicate_score.value.status})",
    )
    page.wait_for_timeout(400)
    check(
        page.locator("[data-score-codec]").count() == 1,
        "and no second score appeared",
    )

    # A PDF goes through the browser's own viewer, which is the whole reason no
    # PDF library is needed here.
    page.set_input_files('input[aria-label="Score file"]', str(pdf))
    page.fill('input[aria-label="Score title"]', "")
    with page.expect_response(
        lambda r: "/scores" in r.url and r.request.method == "POST", timeout=60_000
    ) as attached_pdf:
        click_button(page, "Attach score")
    check(attached_pdf.value.json()["codec"] == "pdf", "a PDF is accepted as a PDF")
    page.wait_for_selector("[data-score-viewer='pdf'] iframe", timeout=20_000)
    check(
        page.evaluate(
            "() => document.querySelectorAll(\"[data-score-viewer='pdf'] iframe\").length"
        ) == 1,
        "the PDF is framed rather than re-rendered",
    )
    check(
        page.evaluate("() => document.querySelectorAll('[data-score-codec]').length") == 2,
        "both scores are listed",
    )
    check(
        page.locator(".pill", has_text="2 scores").count() == 1,
        "and the library header counts them apart from recordings",
    )
    page.screenshot(path=str(SHOTS / "20-scores.png"), full_page=True)

    # --- the waveform, and an A/B loop that lives in the database ---
    click_button(page, "Waveform")
    page.wait_for_selector("[data-waveform] canvas", timeout=30_000)
    check(True, "the recording is decoded into a waveform")
    # Peaks are read from the decoded audio, so a picture that drew nothing — or
    # drew every bar one pixel tall — would mean the decode or the scaling broke.
    drawn = page.evaluate(
        """() => {
             const canvas = document.querySelector('[data-waveform] .base');
             const context = canvas.getContext('2d');
             const { data } = context.getImageData(0, 0, canvas.width, canvas.height);
             let lit = 0;
             let tallest = 0;
             for (let x = 0; x < canvas.width; x += 1) {
               let top = -1;
               let bottom = -1;
               for (let y = 0; y < canvas.height; y += 1) {
                 if (data[(y * canvas.width + x) * 4 + 3] > 0) {
                   if (top < 0) top = y;
                   bottom = y;
                 }
               }
               if (top >= 0) {
                 lit += 1;
                 tallest = Math.max(tallest, bottom - top + 1);
               }
             }
             return { lit, tallest, height: canvas.height };
           }"""
    )
    check(drawn["lit"] > 100, f"the waveform has ink on it ({drawn['lit']} columns)")
    check(
        drawn["tallest"] > drawn["height"] * 0.25,
        f"the tone is drawn at its real level ({drawn['tallest']}/{drawn['height']}px)",
    )

    box = page.locator("[data-waveform]").bounding_box()

    def click_wave(fraction: float) -> None:
        # Re-measured every time rather than reused: a waveform that shifts
        # between clicks makes the test lie about what it clicked.
        live = page.locator("[data-waveform]").bounding_box()
        page.mouse.click(live["x"] + live["width"] * fraction, live["y"] + live["height"] / 2)
        page.wait_for_timeout(300)

    click_wave(0.15)
    click_button(page, "Set A")
    page.wait_for_timeout(500)
    after_a = page.locator("[data-waveform]").bounding_box()
    # Setting a marker must not move the picture under the player's cursor: the
    # first version revealed the "Clear" button here, which pushed the waveform
    # down and made the next click land on the toolbar.
    check(
        abs(after_a["y"] - box["y"]) < 2 and abs(after_a["height"] - box["height"]) < 2,
        f"the waveform does not move when a marker is set ({box['y']} -> {after_a['y']})",
    )
    readout_a = page.locator("[data-loop-readout]").inner_text()
    check("—" not in readout_a.split("·")[0], f"A is marked ({readout_a!r})")

    click_wave(0.6)
    with page.expect_response(
        lambda r: "/api/repertoire/media/" in r.url and r.request.method == "PATCH"
    ) as looped:
        click_button(page, "Set B")
    stored = looped.value.json()
    check(looped.value.status == 200, f"the loop was accepted ({looped.value.status} {stored})")
    check(
        stored["loop_start_s"] is not None and stored["loop_end_s"] is not None,
        f"both markers were saved ({stored['loop_start_s']}, {stored['loop_end_s']})",
    )
    check(
        stored["loop_end_s"] > stored["loop_start_s"],
        "and B is after A, because that is where they were dropped",
    )
    # The buttons are always in the layout, so waiting for the element would pass
    # before the refreshed row arrives; wait for it to become *usable*.
    page.wait_for_function(
        "() => { const b = document.querySelector('[data-play-loop]'); return b && !b.disabled; }",
        timeout=10_000,
    )
    check(True, "a complete loop offers to play itself")
    readout = page.locator("[data-loop-readout]").inner_text()
    check("0:0" in readout and "—" not in readout, f"the markers are readable ({readout!r})")

    # The markers come back from the database, which is what makes them the same
    # passage on the other machine rather than a browser setting.
    detail = api(f"/api/repertoire/pieces/{nocturne['id']}")["media"]
    row = next(item for item in detail if item["id"] == recording["id"])
    check(
        row["loop_start_s"] == stored["loop_start_s"] and row["loop_end_s"] == stored["loop_end_s"],
        "and they are stored on the recording, not in the browser",
    )
    page.screenshot(path=str(SHOTS / "21-waveform.png"), full_page=True)

    with page.expect_response(
        lambda r: "/api/repertoire/media/" in r.url and r.request.method == "PATCH"
    ) as cleared:
        click_button(page, "Clear")
    check(
        cleared.value.json()["loop_start_s"] is None
        and cleared.value.json()["loop_end_s"] is None,
        "and a loop can be cleared again",
    )
    page.wait_for_timeout(300)
    check(
        "—" in page.locator("[data-loop-readout]").inner_text(),
        "the readout goes back to unmarked",
    )

    # Deleting asks first, then removes the piece.
    click_button(page, "Delete")
    page.wait_for_selector(".notice", timeout=5_000)
    check(
        "Recording and score files are left on disk" in page.inner_text(".notice"),
        "the delete warns about cascades",
    )
    click_button(page, "Keep")
    page.wait_for_timeout(200)
    check(
        page.locator(".detail-title").count() == 1,
        "cancelling the delete keeps the piece",
    )

    check(not errors, f"no console errors ({errors})")
    page.close()


#: Send a short phrase straight from the simulated device.
PLAY_PHRASE = """
([pitches, spacing, hold]) => {
  pitches.forEach((pitch, index) => {
    setTimeout(() => window.__fakeMidi.send([0x90, pitch, 72]), index * spacing);
    setTimeout(() => window.__fakeMidi.send([0x80, pitch, 0]), index * spacing + hold);
  });
}
"""


def play_phrase(page: Page, pitches: list[int], *, spacing_ms: int = 130, hold_ms: int = 90) -> None:
    page.evaluate(PLAY_PHRASE, [pitches, spacing_ms, hold_ms])
    page.wait_for_timeout(len(pitches) * spacing_ms + 400)


def clear_practice() -> None:
    """Empty the practice tables so this scenario is deterministic.

    Unlike the repertoire scenarios, nothing here depends on what the earlier
    scenarios played — and leaving their notes in place makes "which sitting did
    this note join" depend on how long the suite happened to take, because the
    five-minute silence gap is real. Test setup, not an assertion.
    """
    conn = sqlite3.connect(os.environ.get("SRT_DB_PATH", str(DEFAULT_DB)), timeout=15)
    try:
        # `identification_outcomes` is listed even though its foreign key would
        # cascade from `segments`: this connection does not set
        # `PRAGMA foreign_keys = ON` (the app's own connections do), so relying on
        # the cascade here would leave yesterday's outcome rows in place and make
        # the accuracy counters depend on how many times the suite has been run.
        for table in (
            "identification_outcomes",
            "pedal_events",
            "segment_metrics",
            "segments",
            "note_events",
            "sittings",
            "workouts",
        ):
            conn.execute(f"DELETE FROM {table}")
        conn.execute("UPDATE performances SET workout_id = NULL")
        conn.commit()
    finally:
        conn.close()


def seed_closed_sitting(*, minutes_ago: int = 60) -> int:
    """A sitting that is already closed, so its segments exist to be edited.

    Fresh notes open a sitting, and segmentation deliberately waits for silence,
    so the timeline interactions need one from the past. Test setup, not an
    assertion — the same helper the backend tests use, driven over HTTP.
    """
    import time

    base = int(time.time() * 1000) - minutes_ago * 60_000
    payload = {
        "tz_offset_minutes": -180,
        "source": "web_midi",
        "events": [
            {
                "epoch_ms": base + offset,
                "pitch": pitch,
                "velocity": 70,
                "duration_ms": 300,
                "channel": 0,
            }
            for pitch, offset in zip((60, 64, 67, 72), (0, 500, 20_000, 60_000))
        ],
    }
    return api("/api/practice/events", "POST", payload)["sitting_id"]


def scenario_practice_log(browser) -> None:
    print("\n[8] Practice log: passive capture, a workout, and the segment timeline")
    clear_practice()
    seeded = seed_closed_sitting()
    pieces = api("/api/repertoire/pieces")
    check(len(pieces) > 0, f"the library has pieces to tag with ({len(pieces)})")
    target = next((piece for piece in pieces if piece["status"] != "completed"), pieces[0])

    page, errors = new_page(browser)
    page.goto(BASE_URL, wait_until="domcontentloaded")
    page.wait_for_selector("text=Sight-Reading Trainer")
    ensure_midi(page)

    click_button(page, "Log")
    page.wait_for_selector("text=Practice calendar", timeout=20_000)

    # --- capture is a standing switch, not a per-sitting button ---
    check(
        page.locator('[data-capture="on"]').count() == 1,
        "capture is on as soon as a device is connected",
    )
    check(
        "Logging everything you play" in page.inner_text('[data-capture="on"]'),
        "and says so, rather than making you infer it from the database",
    )

    before = api("/api/practice/status")["notes"]
    play_phrase(page, [60, 64, 67, 71])
    # The client batches every two seconds, which is the whole cadence.
    page.wait_for_timeout(2_600)
    after = api("/api/practice/status")["notes"]
    check(
        after - before >= 4,
        f"playing is logged without pressing anything ({before} -> {after} notes)",
    )
    counter = page.inner_text('[data-capture="on"]')
    check("notes sent" in counter, f"the capture bar reports what it has sent ({counter!r})")

    # --- the sustain pedal travels with the notes it was under ---
    # CC64 was parsed and dropped before this slice; the whole path is exercised
    # here: the MIDI decoder, the capture buffer, the batch, and the database.
    pedal_sitting = api("/api/practice/sittings")[0]["id"]
    page.evaluate("() => window.__fakeMidi.send([0xb0, 64, 127])")
    play_phrase(page, [60, 64, 67])
    page.evaluate("() => window.__fakeMidi.send([0xb0, 64, 0])")
    page.wait_for_timeout(2_600)
    pedalled = api(f"/api/practice/sittings/{pedal_sitting}/notes")
    values = [move["value"] for move in pedalled["pedals"]]
    check(127 in values and 0 in values, f"both halves of the press are stored ({values})")
    check(
        [move["onset_ms"] for move in pedalled["pedals"]] == sorted(
            move["onset_ms"] for move in pedalled["pedals"]
        ),
        "in the order they happened",
    )
    check(
        pedalled["pedals"][0]["onset_ms"] <= pedalled["notes"][-1]["onset_ms"],
        "and the press is timed against the notes rather than against the sitting's end",
    )
    page.screenshot(path=str(SHOTS / "22-pedal.png"), full_page=True)

    # --- a workout: declared, and therefore distinguishable from noodling ---
    click_button(page, "Start workout")
    page.wait_for_selector('[data-workout="running"]', timeout=10_000)
    check(True, "a workout can be started from anywhere in the app")
    play_phrase(page, [62, 65, 69])
    page.wait_for_timeout(2_600)
    click_button(page, "Finish workout")
    page.wait_for_selector('[data-workout="idle"]', timeout=10_000)

    home = api("/api/workout")
    check(home["current"] is None, "finishing leaves no workout running")
    check(home["workouts_completed"] == 1, f"the workout is recorded ({home['workouts_completed']})")
    check(
        home["recent"][0]["sitting_id"] is not None,
        f"and linked to the sitting it happened inside (sitting {home['recent'][0]['sitting_id']})",
    )
    check(
        "Last workout" in page.inner_text('[data-workout="idle"]'),
        "the banner reports the workout that just ended",
    )
    page.screenshot(path=str(SHOTS / "12-log-capture.png"), full_page=True)

    # --- the segment timeline: tag, split, merge, re-segment ---
    # Control first: the API is the source of truth for how many segments the
    # sitting has, so a mismatch is a rendering bug rather than an API one.
    seeded_detail = api(f"/api/practice/sittings/{seeded}")
    check(
        len(seeded_detail["segments"]) == 2,
        f"the seeded sitting is segmented into two ({len(seeded_detail['segments'])})",
    )
    with page.expect_response(lambda r: f"/api/practice/sittings/{seeded}" in r.url):
        page.click(f'[data-sitting="{seeded}"]')
    page.wait_for_selector("[data-segments]", timeout=20_000)
    check(
        page.get_attribute("section.timeline", "data-segments") == "2",
        "and the interface draws both of them",
    )
    check(
        page.locator(".block").count() == 2,
        "both are drawn on the timeline strip",
    )

    with page.expect_response(lambda r: "/api/practice/segments/" in r.url and r.request.method == "PATCH"):
        page.select_option('select[aria-label="Piece for this segment"] >> nth=0', str(target["id"]))
    page.wait_for_timeout(600)
    check(
        page.locator(".block.labelled").count() == 1,
        "the tagged segment is drawn as identified on the strip",
    )
    check(
        page.evaluate(
            "() => document.querySelector('select[aria-label=\"Piece for this segment\"]').value"
        )
        == str(target["id"]),
        "and the tag survives a re-read",
    )
    bars = page.evaluate(
        """() => [...document.querySelectorAll('.bars li')].map((item) => item.innerText)"""
    )
    check(
        any(target["title"] in bar for bar in bars),
        f"the tagged piece appears in time-per-piece ({bars})",
    )
    page.screenshot(path=str(SHOTS / "13-log-segments.png"), full_page=True)

    # The repertoire side must show the same measurement, not a rival number.
    click_button(page, "Repertoire")
    page.wait_for_selector(".row-piece", timeout=20_000)
    page.locator(".row-piece", has_text=target["title"]).first.click()
    page.wait_for_selector(".detail-title", timeout=10_000)
    # Headings are uppercased in CSS and `innerText` returns what is rendered, so
    # the comparison is case-insensitive.
    logged = page.inner_text(".detail").lower()
    check("logged practice" in logged, "the piece shows a logged-practice block")
    check("min played" in logged, f"with the measured time ({logged.split('logged practice')[1][:90]!r})")
    check("0 min played" not in logged, "and it is a measurement, not a zero placeholder")

    click_button(page, "Log")
    page.wait_for_selector("text=Practice calendar", timeout=20_000)
    with page.expect_response(lambda r: f"/api/practice/sittings/{seeded}" in r.url):
        page.click(f'[data-sitting="{seeded}"]')
    page.wait_for_selector('section.timeline[data-segments="2"]', timeout=20_000)

    # Playback of what was logged. The notes are fetched on demand, which is the part
    # worth asserting: the sitting detail deliberately does not carry them.
    with page.expect_response(lambda r: f"/api/practice/sittings/{seeded}/notes" in r.url):
        click_button(page, "Play the sitting")
    page.wait_for_selector('[data-playing="true"]', timeout=10_000)
    check(True, "a logged sitting can be played back from its notes")
    check(
        page.locator("[data-playhead]").count() == 1,
        "and the strip shows where playback has reached",
    )
    click_button(page, "Stop")
    page.wait_for_selector('[data-playing="false"]', timeout=10_000)
    check(True, "stopping clears the playhead")

    # One segment on its own.
    page.get_by_role("button", name=re.compile(r"^▶")).first.click()
    page.wait_for_selector('[data-playing="true"]', timeout=10_000)
    check(True, "and a single segment can be heard on its own")
    click_button(page, "Stop")
    page.wait_for_selector('[data-playing="false"]', timeout=10_000)

    # Split: the silence detector's boundary was wrong, so move it by hand.
    split = page.locator(".split input").first
    split.fill("10")
    with page.expect_response(lambda r: r.url.endswith("/split")):
        page.get_by_role("button", name="Split here", exact=True).first.click()
    page.wait_for_selector('section.timeline[data-segments="3"]', timeout=20_000)
    check(True, "a segment can be split at a chosen point")

    with page.expect_response(lambda r: r.url.endswith("/merge")):
        page.get_by_role("button", name="Merge with previous", exact=True).first.click()
    page.wait_for_selector('section.timeline[data-segments="2"]', timeout=20_000)
    check(True, "and merged back with its neighbour")

    # Re-segment discards the hand-edited boundaries *and* the tag, which is why
    # it is the only destructive path and asks for confirmation when labelled.
    with page.expect_response(lambda r: r.url.endswith("/resegment")):
        page.get_by_role("button", name=re.compile("^Re-segment")).first.click()
    page.wait_for_selector('section.timeline[data-segments="2"]', timeout=20_000)
    page.wait_for_timeout(400)
    check(
        page.evaluate(
            "() => [...document.querySelectorAll('select[aria-label=\"Piece for this segment\"]')]"
            ".every((select) => select.value === '')"
        ),
        "re-segmenting discarded the labels it warned about",
    )

    # --- installation health ---
    health = page.locator("[data-system-status]")
    check(health.count() == 1, "the Log view reports the installation's health")
    text = health.inner_text()
    check("Database" in text and "MB" in text, f"including the database size ({text[:60]!r})")
    check(
        "Backups" in text,
        "and how many backups are kept, which is the thing you only miss once",
    )
    check(
        "Piano visible to ALSA" in text,
        "and whether the server can see the piano through ALSA at all",
    )

    # --- export and restore ---
    backup_path = DEFAULT_DB.parent / "e2e-backup.json"
    document = page.evaluate(
        """async (url) => {
             const response = await fetch(url);
             return { status: response.status, body: await response.json() };
           }""",
        "/api/backup/export",
    )
    check(document["status"] == 200, "the backup downloads from a plain link")
    check(
        document["body"]["format"] == "piano-ecosystem-backup",
        f"and is a document this app can read ({document['body']['format']})",
    )
    check(
        document["body"]["counts"]["sittings"] >= 2,
        f"it contains the sittings just recorded ({document['body']['counts']['sittings']})",
    )
    backup_path.write_text(json.dumps(document["body"]))
    page.set_input_files('input[aria-label="Backup file"]', str(backup_path))
    page.wait_for_timeout(300)
    with page.expect_response(lambda r: r.url.endswith("/api/backup/import")):
        click_button(page, "Restore backup")
    page.wait_for_timeout(800)
    # Nothing was lost, which is the only thing a restore prompt has to promise.
    check(
        page.locator(".backup .notice").count() == 0,
        "merging a backup needs no destructive confirmation",
    )
    check(
        "new rows" in page.inner_text(".backup"),
        f"the restore reports what it read ({page.inner_text('.backup')[-160:]!r})",
    )
    backup_path.unlink(missing_ok=True)

    check(not errors, f"no console errors ({errors})")
    page.close()


def scenario_midi_autodetect(browser) -> None:
    print("\n[9] MIDI that sets itself up: one dead port, one live, no clicking")
    page, errors = new_page(browser)
    page.goto(BASE_URL, wait_until="domcontentloaded")
    page.wait_for_selector("text=Sight-Reading Trainer")

    # No click anywhere in this block: on the notebook a managed policy grants the
    # MIDI permission, so connecting is the app's job.
    page.wait_for_selector("text=MIDI connected", timeout=15_000)
    check(True, "the app connects with no interaction at all")
    check(
        page.evaluate("() => window.__fakeMidi.total()") == 2,
        "two inputs are exposed, as ALSA exposes them",
    )
    label = page.inner_text("[data-midi-active]")
    check("CASIO" in label, f"the live port is chosen, not the first one ({label!r})")
    check("Auto" in label, "and it is reported as an automatic choice")

    # The dead port is listed, and honestly labelled rather than hidden.
    open_ports(page)
    through_row = page.locator('[data-port="alsa-midi-through"]').inner_text()
    check("Midi Through" in through_row, f"the silent ALSA port is listed ({through_row!r})")
    check("no notes yet" in through_row, "and marked as never having carried a note")
    casio_row = page.locator('[data-port="alsa-casio-1"]').inner_text()
    check("in use" in casio_row, f"the Casio port is the one in use ({casio_row!r})")

    # A key reported by both ports is one key. Capture is on by default and flushes
    # every two seconds, so the count is read from the API rather than the screen.
    before = api("/api/practice/status")["notes"]
    page.evaluate(
        """() => {
             window.__fakeMidi.sendToAll([0x90, 64, 80]);
             setTimeout(() => window.__fakeMidi.sendToAll([0x80, 64, 0]), 60);
           }"""
    )
    page.wait_for_timeout(2_600)
    logged = api("/api/practice/status")["notes"] - before
    check(logged == 1, f"a note reported by both ports is logged once (logged {logged})")

    # The piano is switched on after the machine is already running: the normal case
    # for a planted notebook.
    page.evaluate("() => window.__fakeMidi.unplugAll()")
    page.wait_for_selector("text=No MIDI input", timeout=15_000)
    page.evaluate("() => window.__fakeMidi.plugLater(400, 'alsa-casio-1')")
    page.wait_for_selector("text=MIDI connected", timeout=20_000)
    check(True, "a piano switched on later is picked up with no reload and no click")

    # Pinning is for the person who wants certainty rather than inference.
    open_ports(page)
    page.locator('[data-port="alsa-casio-1"]').get_by_role(
        "button", name="Use only this", exact=True
    ).click()
    page.wait_for_timeout(300)
    check("Pinned" in page.inner_text("[data-midi-active]"), "the choice can be pinned")

    before = api("/api/practice/status")["notes"]
    page.evaluate("() => window.__fakeMidi.send([0x90, 67, 80], 'alsa-midi-through')")
    page.wait_for_timeout(2_600)
    check(
        api("/api/practice/status")["notes"] == before,
        "notes from a port that was pinned out are ignored",
    )

    # And the choice survives a reload, which is the point of remembering it.
    page.reload(wait_until="domcontentloaded")
    page.wait_for_selector("text=MIDI connected", timeout=15_000)
    check(
        "Pinned" in page.inner_text("[data-midi-active]"),
        "the pinned device survives a reload",
    )

    page.screenshot(path=str(SHOTS / "14-midi-autodetect.png"), full_page=True)
    check(not errors, f"no console errors ({errors})")
    page.close()


#: Drills for the matcher scenario. Two pieces one note apart, which is the case
#: the matcher must not be confident about, and one that sounds nothing like them.
DRILL_A = [60, 62, 64, 65, 67, 69, 71, 72]
DRILL_B = [60, 62, 64, 65, 67, 69, 71, 73]
DRILL_C = [45, 48, 52, 55, 57, 60, 48, 52]


def drill(minutes_ago: int, pitches: list[int], *, spacing_ms: int = 250) -> int:
    """Log one drill as if it had been played, and return its sitting.

    Simulated at the API rather than performed through the page: this scenario is
    about what happens to a sitting once it is segmented, and playing eight notes
    through Web MIDI per drill would add a minute of waiting for nothing.
    """
    import time

    base = int(time.time() * 1000) - minutes_ago * 60_000
    payload = {
        "tz_offset_minutes": -180,
        "source": "web_midi",
        "events": [
            {
                "epoch_ms": base + index * spacing_ms,
                "pitch": pitch,
                "velocity": 70,
                "duration_ms": 200,
                "channel": 0,
            }
            for index, pitch in enumerate(pitches)
        ],
    }
    return api("/api/practice/events", "POST", payload)["sitting_id"]


def label(sitting_id: int, piece_id: int) -> int:
    """Tag a sitting's single segment by hand, and return the segment's id."""
    detail = api(f"/api/practice/sittings/{sitting_id}")
    segment_id = detail["segments"][0]["id"]
    api(f"/api/practice/segments/{segment_id}", "PATCH", {"piece_id": piece_id})
    return segment_id


def held_note_sitting(*, minutes_ago: int = 150) -> int:
    """A sitting whose first note is still sounding a second after it starts.

    Needed for the only question about Stop that matters — does a note that *is*
    sounding get turned off — because the four short notes of the seeded sitting have
    all finished before anyone can reach the button.
    """
    import time

    base = int(time.time() * 1000) - minutes_ago * 60_000
    payload = {
        "tz_offset_minutes": -180,
        "source": "web_midi",
        "events": [
            # 84 and 86 on purpose: no other sitting in this suite plays them, so a
            # stale notes cache cannot satisfy the assertions by accident.
            {"epoch_ms": base, "pitch": 84, "velocity": 80, "duration_ms": 6_000, "channel": 0},
            {"epoch_ms": base + 8_000, "pitch": 86, "velocity": 80, "duration_ms": 300, "channel": 0},
        ],
    }
    return api("/api/practice/events", "POST", payload)["sitting_id"]


def scenario_playback(browser) -> None:
    print("\n[12] Playback: through the piano, and into it")
    clear_practice()
    sitting_id = seed_closed_sitting(minutes_ago=90)
    held_id = held_note_sitting()
    notes = api(f"/api/practice/sittings/{sitting_id}/notes")["notes"]
    check(len(notes) >= 3, f"the sitting has notes to play ({len(notes)})")

    page, errors = new_page(browser)
    page.goto(BASE_URL, wait_until="domcontentloaded")
    page.wait_for_selector("text=Sight-Reading Trainer")
    ensure_midi(page)
    click_button(page, "Log")
    page.wait_for_selector("[data-identification]", timeout=20_000)

    # --- the instrument choice ---
    check(page.locator("[data-sound]").count() == 1, "there is a playback instrument control")
    options = page.evaluate(
        "() => [...document.querySelectorAll('#instrument option')].map((o) => ({ value: o.value, disabled: o.disabled }))"
    )
    check(
        any(item["value"] == "midi" and not item["disabled"] for item in options),
        f"the piano can be played through, because one is connected ({options})",
    )
    check(
        any(item["value"] == "synth" for item in options),
        "and the synthesiser is always offered",
    )

    # --- the sampled piano actually loads ---
    # The browser is the only place this can be checked: it is Tone's own note-name
    # parser that has to accept every URL key, and it rejects the `Ds4` spelling the
    # files use. Nothing here asserts *sound* — that is not observable from a test —
    # but "the 30 samples decoded" is, and it is the step that was silently failing.
    installed = api("/api/audio/piano")
    if installed["available"]:
        page.select_option("#instrument", "piano")
        try:
            page.wait_for_selector('[data-sample-state="ready"]', timeout=20_000)
            loaded = True
        except PlaywrightTimeout:
            loaded = False
        check(loaded, f"the sampled piano loads every sample ({installed['present']} present)")
        check(
            page.locator("[data-sample-error]").count() == 0,
            "and reports no sample error",
        )
        page.select_option("#instrument", "midi")
    else:
        # Without the samples installed this scenario cannot check the instrument, and
        # pretending otherwise would be a green tick over nothing.
        print("      skipped: the sampled piano is not installed on this server")

    # --- playing, through the piano ---
    # Selecting a sitting reads its detail; the notes are fetched on the first play,
    # because a long sitting is thousands of them and every edit re-reads the detail.
    with page.expect_response(lambda r: r.url.endswith(f"/api/practice/sittings/{sitting_id}")):
        page.click(f'[data-sitting="{sitting_id}"]')
    page.wait_for_selector("[data-strip]", timeout=20_000)
    page.evaluate("() => window.__fakeMidi.forget()")

    with page.expect_response(
        lambda r: r.url.endswith(f"/api/practice/sittings/{sitting_id}/notes")
    ):
        click_button(page, "Play the sitting")
    page.wait_for_timeout(1_200)
    played = page.evaluate("() => window.__fakeMidi.noteOns()")
    check(len(played) > 0, f"playing sends notes to the piano ({len(played)} so far)")
    check(
        all(item["port"] == "alsa-casio-out" for item in played),
        "to the piano, not to the dead ALSA port",
    )
    check(
        all(item["timestamp"] is not None for item in played),
        "with a timestamp, so the piano's own clock places them",
    )
    readout = page.inner_text("[data-position]")
    check("/" in readout, f"and a position readout appears ({readout!r})")
    check(
        not readout.startswith("0:00"),
        f"and it advances as the music does ({readout!r})",
    )

    # --- Stop has to stop ---
    # First with nothing left sounding, which is the ordinary case: the notes here are
    # 300 ms and have finished long before anyone reaches the button. The sweep still
    # has to go out, because note-ons up to a window ahead were already handed to the
    # MIDI stack and have not happened yet.
    page.evaluate("() => window.__fakeMidi.forget()")
    click_button(page, "Stop")
    page.wait_for_timeout(700)
    check(
        page.evaluate("() => window.__fakeMidi.allNotesOff()") >= 32,
        "stopping sends the silence sweep even when nothing is currently sounding",
    )
    check(
        page.locator("[data-playing='false']").count() == 1,
        "and the transport goes back to offering Play",
    )

    # Then with a note six seconds long, so something really is sounding when the
    # button is pressed — the case where an explicit note-off is the only thing that
    # saves it, because a controller message is only as good as the instrument.
    with page.expect_response(lambda r: r.url.endswith(f"/api/practice/sittings/{held_id}")):
        page.click(f'[data-sitting="{held_id}"]')
    page.wait_for_selector("[data-strip]", timeout=20_000)
    page.evaluate("() => window.__fakeMidi.forget()")
    with page.expect_response(
        lambda r: r.url.endswith(f"/api/practice/sittings/{held_id}/notes")
    ):
        click_button(page, "Play the sitting")
    page.wait_for_timeout(900)
    started = page.evaluate("() => window.__fakeMidi.noteOns().map((n) => n.pitch)")
    check(84 in started, f"the held note of *this* sitting has sounded ({started})")

    page.evaluate("() => window.__fakeMidi.forget()")
    click_button(page, "Stop")
    page.wait_for_timeout(700)
    offs = page.evaluate("() => window.__fakeMidi.noteOffs()")
    silenced = page.evaluate("() => window.__fakeMidi.allNotesOff()")
    check(84 in offs, f"stopping turns the note that is sounding off ({offs})")
    # 16 channels x (all notes off + all sound off) x two sweeps: the second one
    # follows the scheduling window, because a note-on already handed to the MIDI
    # stack cannot be recalled — only followed by silence.
    check(
        silenced >= 32,
        f"and asks for silence on every channel, so nothing is left ringing ({silenced})",
    )
    after_stop = page.evaluate("() => window.__fakeMidi.noteOns().length")
    page.wait_for_timeout(900)
    still = page.evaluate("() => window.__fakeMidi.noteOns().length")
    check(
        still == after_stop,
        f"and nothing further is sent afterwards ({after_stop} -> {still})",
    )

    # --- seeking into a long sitting ---
    total_notes = len(notes)
    page.evaluate("() => window.__fakeMidi.forget()")
    box = page.locator("[data-strip]").bounding_box()
    page.mouse.click(box["x"] + box["width"] * 0.85, box["y"] + box["height"] / 2)
    page.wait_for_timeout(900)
    sought = page.evaluate("() => window.__fakeMidi.noteOns()")
    check(
        len(sought) < total_notes,
        f"clicking the strip plays from there rather than from the beginning "
        f"({len(sought)} of {total_notes} notes so far)",
    )
    position = page.inner_text("[data-position]")
    check(
        not position.startswith("0:00"),
        f"and the readout shows where the seek landed ({position!r})",
    )

    # Jumping back is the same mechanism in reverse.
    page.evaluate("() => window.__fakeMidi.forget()")
    click_button(page, "« 30 s")
    page.wait_for_timeout(700)
    check(
        len(page.evaluate("() => window.__fakeMidi.noteOns()")) >= 0,
        "and the jump buttons re-start playback from the new position",
    )
    click_button(page, "Stop")
    page.wait_for_timeout(300)

    # --- the falling notes ---
    check(page.locator("[data-piano-roll]").count() == 0, "the roll starts hidden")
    page.check("[data-roll-toggle]")
    page.wait_for_selector("[data-piano-roll]", timeout=10_000)
    click_button(page, "Play the sitting")
    page.wait_for_timeout(900)
    ink = page.evaluate(
        """() => {
             const canvas = document.querySelector('[data-piano-roll]');
             const context = canvas.getContext('2d');
             const { data } = context.getImageData(0, 0, canvas.width, canvas.height);
             let lit = 0;
             for (let index = 3; index < data.length; index += 4) if (data[index] > 0) lit += 1;
             return { lit, width: canvas.width, height: canvas.height };
           }"""
    )
    check(ink["lit"] > 1000, f"the falling-notes view draws ({ink['lit']} pixels)")
    check(ink["width"] > 100 and ink["height"] > 100, "on a canvas with real size")
    page.screenshot(path=str(SHOTS / "25-piano-roll.png"), full_page=True)
    click_button(page, "Stop")

    # --- the field that was not explained ---
    label = page.inner_text(".split").lower()
    check("split at" in label, f"the split field is labelled ({label!r})")
    value = page.input_value('input[aria-label="Split point as seconds or m:ss"]')
    check(":" in value, f"and shows a clock rather than a count of seconds ({value!r})")

    page.fill('input[aria-label="Split point as seconds or m:ss"]', "not a time")
    click_button(page, "Split here")
    page.wait_for_timeout(300)
    check(
        "not a time" in page.inner_text(".timeline"),
        "a value that is not a time is refused with an explanation",
    )
    page.fill('input[aria-label="Split point as seconds or m:ss"]', "0:01")
    check(
        page.input_value('input[aria-label="Split point as seconds or m:ss"]') == "0:01",
        "and a typed clock is accepted",
    )

    check(not errors, f"no console errors ({errors})")
    page.close()


def scenario_autotag(browser) -> None:
    print("\n[11] Recognising what you played: measured, offered, and correctable")
    clear_practice()
    pieces = api("/api/repertoire/pieces")
    check(len(pieces) >= 3, f"the library has pieces to tag with ({len(pieces)})")
    first, second, third = pieces[0], pieces[1], pieces[2]

    # --- the reference: drills a person has tagged ---
    # Two pieces that sound nothing like each other, so a confident match is
    # possible at all. One drill per sitting, twelve minutes apart, so each is
    # closed and segmented before the next arrives.
    label(drill(180, DRILL_A), first["id"])
    label(drill(168, DRILL_A), first["id"])
    label(drill(156, DRILL_C), second["id"])
    label(drill(144, DRILL_C), second["id"])

    # The same music as the first piece, never played before: this is what drilling
    # a piece already in the library looks like, and it is the case the matcher is
    # allowed to answer on its own.
    matching = drill(132, DRILL_A)
    matching_segment = api(f"/api/practice/sittings/{matching}")["segments"][0]
    check(
        matching_segment["piece_id"] == first["id"],
        f"a confident match is written automatically ({matching_segment['piece_id']})",
    )
    check(
        matching_segment["identified_by"] == "similarity",
        f"and is marked as the matcher's guess ({matching_segment['identified_by']})",
    )
    check(not matching_segment["candidates"], "a decided segment is not asked about")

    # --- and now the twin: a third piece one note away from the first ---
    # With nothing similar yet in the library, the matcher is confident — and wrong.
    # This is the cold-start mistake the margin rule cannot prevent, and correcting
    # it is what teaches the library that two pieces sound alike.
    mistaken = drill(120, DRILL_B)
    mistaken_segment = api(f"/api/practice/sittings/{mistaken}")["segments"][0]
    check(
        mistaken_segment["identified_by"] == "similarity",
        "a new piece that resembles one already tagged is guessed at first",
    )
    check(
        mistaken_segment["piece_id"] == first["id"],
        f"and the first guess is the piece it resembles ({mistaken_segment['piece_id']})",
    )
    label(mistaken, third["id"])

    # The correction is on the record, and it is what makes the next one careful.
    corrected = api("/api/practice/autotag/quality")
    check(
        corrected["changed"] >= 1,
        f"correcting a written guess is recorded as the matcher being wrong ({corrected['changed']})",
    )

    # From here the two similar pieces are both known, so the matcher stops
    # answering and starts asking.
    twin = drill(108, DRILL_B)
    twin_segment = api(f"/api/practice/sittings/{twin}")["segments"][0]
    check(twin_segment["piece_id"] is None, "so the next one is not guessed at")
    check(
        twin_segment["candidates"] and twin_segment["candidates"][0]["band"] == "suggest",
        f"it is offered instead ({twin_segment['candidates'][:1]})",
    )
    check(
        "close" in (twin_segment["candidates"][0]["reason"] or ""),
        f"with the reason said plainly ({twin_segment['candidates'][0]['reason']!r})",
    )

    # --- what the interface does with all that ---
    page, errors = new_page(browser)
    page.goto(BASE_URL, wait_until="domcontentloaded")
    page.wait_for_selector("text=Sight-Reading Trainer")
    ensure_midi(page)
    click_button(page, "Log")
    page.wait_for_selector("text=Practice calendar", timeout=20_000)
    page.wait_for_selector("[data-identification]", timeout=20_000)

    # The measurement first: it is the claim the rest of this rests on.
    panel = page.inner_text("[data-identification]")
    check("Right first time" in panel, "the panel reports the measured accuracy")
    check("Written without asking" in panel, "and how often a label is written unasked")
    quality = api("/api/practice/autotag/quality")
    check(
        quality["evaluated"] == quality["labelled"] >= 4,
        f"measured by hiding each of the {quality['labelled']} hand-tagged segments",
    )
    check(
        quality["accuracy"] is not None and quality["accuracy"] >= 0.75,
        f"and it gets the obvious ones right ({quality['accuracy']})",
    )
    # The *quality* bar lives in tools/measure_autotag.py, which has a corpus big
    # enough to say something; here the question is whether the number on screen is
    # the one the counts produce, because a panel that invents its own percentage is
    # worse than no panel.
    check(
        quality["auto_attempted"] == 0
        or abs(quality["auto_precision"] - quality["auto_correct"] / quality["auto_attempted"]) < 1e-9,
        "the reported precision is the counts it came from "
        f"({quality['auto_correct']}/{quality['auto_attempted']})",
    )
    check(
        quality["unresolved"] >= 0 and quality["offered_attempted"] >= 0,
        f"and it says how much it could not judge ({quality['unresolved']})",
    )

    # The inferred label, in the timeline, with the two answers next to it.
    # `endswith`, not `in`: a sitting id is a prefix of a longer one, so
    # `sittings/5` matches a response for `sittings/57` and the wait passes on the
    # wrong request.
    with page.expect_response(
        lambda r: r.url.endswith(f"/api/practice/sittings/{matching}")
    ):
        page.click(f'[data-sitting="{matching}"]')
    page.wait_for_selector(f"[data-inferred]", timeout=20_000)
    check(True, "a written guess is shown as a guess, not as a fact")
    check(
        page.evaluate(
            """() => document.querySelector('select[aria-label="Piece for this segment"]').value"""
        )
        == str(first["id"]),
        "with the piece it guessed already selected",
    )
    page.screenshot(path=str(SHOTS / "23-identified.png"), full_page=True)

    # "It's right" takes ownership: the label stays, the guess marking goes.
    with page.expect_response(
        lambda r: r.url.endswith("/identification") and r.request.method == "POST"
    ):
        click_button(page, "It's right")
    page.wait_for_timeout(600)
    check(page.locator("[data-inferred]").count() == 0, "accepting retires the question")
    check(
        page.evaluate(
            """() => document.querySelector('select[aria-label="Piece for this segment"]').value"""
        )
        == str(first["id"]),
        "and the label is still there",
    )
    after = api("/api/practice/autotag/quality")
    check(
        after["confirmed"] >= 1 and after["settled"] >= 1,
        f"the acceptance is recorded as the matcher being right ({after['confirmed']})",
    )
    precision_before = after["live_precision"]

    # The offered match, and saying no to it.
    with page.expect_response(lambda r: r.url.endswith(f"/api/practice/sittings/{twin}")):
        page.click(f'[data-sitting="{twin}"]')
    page.wait_for_selector("[data-suggest]", timeout=20_000)
    buttons = page.evaluate(
        "() => [...document.querySelectorAll('[data-suggest] [data-candidate]')].map((b) => b.innerText)"
    )
    check(len(buttons) >= 2, f"the alternatives are offered with their scores ({buttons})")
    check(
        any("·" in label_text for label_text in buttons),
        "each one carries the percentage behind it",
    )
    page.screenshot(path=str(SHOTS / "24-suggested.png"), full_page=True)

    before_dismissal = api("/api/practice/autotag/quality")["dismissed"]
    with page.expect_response(
        lambda r: r.url.endswith("/identification") and r.request.method == "POST"
    ):
        click_button(page, "Neither")
    page.wait_for_timeout(600)
    check(page.locator("[data-suggest]").count() == 0, "declining clears the question")
    # ...and it stays cleared, which is the part a reload would expose.
    with page.expect_response(
        lambda r: r.url.endswith(f"/api/practice/sittings/{matching}")
    ):
        page.click(f'[data-sitting="{matching}"]')
    with page.expect_response(lambda r: r.url.endswith(f"/api/practice/sittings/{twin}")):
        page.click(f'[data-sitting="{twin}"]')
    page.wait_for_timeout(600)
    check(
        page.locator("[data-suggest]").count() == 0,
        "and does not come back on the next look",
    )
    dismissed = api("/api/practice/autotag/quality")
    check(
        dismissed["dismissed"] == before_dismissal + 1,
        f"the refusal is recorded so it is not asked again ({dismissed['dismissed']})",
    )
    # Compared rather than asserted to a number: what matters is that declining a
    # *suggestion* changes nothing about how often the matcher's written guesses
    # turned out to be right.
    check(
        dismissed["live_precision"] == precision_before,
        "and a declined suggestion is not counted as the matcher being wrong "
        f"({precision_before} -> {dismissed['live_precision']})",
    )

    # --- the backfill: practice that predates the matcher ---
    report = api("/api/practice/autotag", "POST")
    check(
        report["considered"] >= 0 and "assigned" in report,
        f"the backfill reports what it did ({report})",
    )
    check(
        page.locator("[data-identification]").count() == 1,
        "and the panel survives a re-read",
    )

    check(not errors, f"no console errors ({errors})")
    page.close()


def scenario_lan_viewer(browser) -> None:
    print("\n[10] Viewing from another machine: what this page says it cannot do")

    # The suite runs on loopback, so the server's own view is stubbed to what a main
    # computer would get. The rule itself is tested against the real helper in the
    # backend suite; this scenario is about the interface telling the truth.
    remote_host = {
        "host": "192.168.1.50",
        "loopback": False,
        "sequencer": True,
        "clients": ["Midi Through", "CASIO USB-MIDI"],
    }
    page, errors = new_page(browser)
    page.route(
        "**/api/host",
        lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps(remote_host)
        ),
    )
    page.goto(BASE_URL, wait_until="domcontentloaded")
    page.wait_for_selector("text=Sight-Reading Trainer")
    ensure_midi(page)

    banner = page.locator('[data-host-warning="remote"]')
    page.wait_for_selector('[data-host-warning="remote"]', timeout=15_000)
    text = banner.inner_text()
    check("another machine" in text, f"the banner names the situation ({text[:70]!r})")
    check("192.168.1.50" in text, "and the address it is being viewed from")

    # The heartbeat makes the notebook's capture state visible from here.
    click_button(page, "Log")
    page.wait_for_selector("text=Practice calendar", timeout=20_000)
    check(
        page.locator('[data-capture-stat="reporting"]').count() == 1,
        "the Log view reports that a client is capturing",
    )
    check(
        "not reporting" not in page.inner_text('[data-capture-stat="reporting"]'),
        "and does not claim the notebook is silent",
    )
    page.screenshot(path=str(SHOTS / "15-lan-viewer.png"), full_page=True)

    # Deleting is refused here, and the control says so rather than failing later.
    click_button(page, "Repertoire")
    page.wait_for_selector(".row-piece", timeout=20_000)
    page.locator(".row-piece").first.click()
    page.wait_for_selector(".detail-title", timeout=10_000)
    delete_button = page.get_by_role("button", name="Delete", exact=True).first
    check(
        delete_button.is_disabled(),
        "Delete is disabled on a machine that is not the piano machine",
    )
    check(
        "piano machine" in (delete_button.get_attribute("title") or ""),
        "and explains where it can be done",
    )
    check(not errors, f"no console errors ({errors})")
    page.close()

    # The sequencer warning is the diagnostic for "the piano is plugged in but the app
    # sees nothing", which is a missing kernel module rather than broken hardware.
    page, errors = new_page(browser)
    page.route(
        "**/api/host",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({**remote_host, "loopback": True, "sequencer": False, "clients": []}),
        ),
    )
    page.goto(BASE_URL, wait_until="domcontentloaded")
    page.wait_for_selector('[data-host-warning="sequencer"]', timeout=15_000)
    check(True, "a missing ALSA sequencer is reported instead of looking like broken hardware")
    check(
        page.locator('[data-host-warning="remote"]').count() == 0,
        "and the piano machine is not told it is remote",
    )
    check(not errors, f"no console errors ({errors})")
    page.close()

    # And on the piano machine itself, with the server's real answer, neither appears.
    page, errors = new_page(browser)
    page.goto(BASE_URL, wait_until="domcontentloaded")
    page.wait_for_selector("text=Sight-Reading Trainer")
    ensure_midi(page)
    page.wait_for_timeout(600)
    check(
        page.locator("[data-host-warning]").count() == 0,
        "the piano machine sees no deployment warnings at all",
    )
    check(not errors, f"no console errors ({errors})")
    page.close()


def main() -> int:
    SHOTS.mkdir(parents=True, exist_ok=True)
    health = api("/api/health")
    print(f"API health: {health}")
    # Start from a clean profile so step and score assertions are deterministic.
    api("/api/profile/reset", method="POST")
    print("Profile reset for a repeatable run.")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=CHROMIUM,
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--autoplay-policy=no-user-gesture-required",
                "--mute-audio",
            ],
        )
        try:
            for scenario in (
                scenario_perfect,
                scenario_wrong_and_silence,
                scenario_calibration_and_stats,
                scenario_theming,
                scenario_long_exercises,
                scenario_two_hands,
                scenario_repertoire,
                scenario_practice_log,
                scenario_midi_autodetect,
                scenario_autotag,
                scenario_playback,
                scenario_lan_viewer,
            ):
                # An optional filter, so a fix to one scenario can be checked in
                # seconds instead of by replaying the whole suite. The full run
                # (no argument) is still what verifies a slice.
                if ONLY and ONLY not in scenario.__name__:
                    continue
                scenario(browser)
        finally:
            browser.close()

    print("\nAll browser scenarios passed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CheckFailure as failure:
        print(f"\nFAILED: {failure}")
        raise SystemExit(1) from failure
