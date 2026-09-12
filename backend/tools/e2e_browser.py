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

    backend/.venv/bin/python backend/tools/e2e_browser.py [base_url]
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, sync_playwright

BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
CHROMIUM = "/usr/bin/chromium"
SHOTS = Path(__file__).resolve().parent.parent / "screenshots"

#: Injected before every page script. Mimics a Casio PX-870 enough for the app's
#: own MIDI layer to treat it as a real device.
FAKE_MIDI = """
(() => {
  const input = {
    id: 'fake-px870',
    name: 'CASIO PX-870 (simulated)',
    manufacturer: 'CASIO',
    type: 'input',
    state: 'connected',
    connection: 'open',
    onmidimessage: null,
  };
  const inputs = new Map([[input.id, input]]);
  const access = {
    inputs: {
      forEach: (callback) => inputs.forEach((value) => callback(value)),
      get: (key) => inputs.get(key),
      size: inputs.size,
    },
    outputs: { forEach: () => {}, size: 0 },
    sysexEnabled: false,
    onstatechange: null,
  };
  navigator.requestMIDIAccess = async () => access;
  window.__fakeMidi = {
    send(bytes) {
      if (typeof input.onmidimessage !== 'function') return false;
      input.onmidimessage({ data: new Uint8Array(bytes), timeStamp: performance.now() });
      return true;
    },
    ready() {
      return typeof input.onmidimessage === 'function';
    },
  };
})();
"""

#: Schedule a whole performance from inside the page, anchored to `performance.now()`.
#: The same clock the app uses for onsets, so timing is exact apart from the
#: polling delay in detecting that playback started.
PLAY_NOTES = """
([notes, velocity, holdMs]) => {
  const anchor = performance.now();
  window.__playTimers = [];
  for (const note of notes) {
    const at = Math.max(0, note.onset_s * 1000);
    window.__playTimers.push(
      setTimeout(() => window.__fakeMidi.send([0x90, note.pitch, velocity]), at),
      setTimeout(() => window.__fakeMidi.send([0x80, note.pitch, 0]), at + holdMs),
    );
  }
  return anchor;
}
"""

#: Cancel any notes still queued from the previous run. Without this, a long
#: exercise keeps firing notes into whatever the test does next.
CANCEL_PLAYBACK = """
() => {
  (window.__playTimers || []).forEach(clearTimeout);
  window.__playTimers = [];
  return true;
}
"""


class CheckFailure(AssertionError):
    pass


def check(condition: bool, message: str) -> None:
    if not condition:
        raise CheckFailure(message)
    print(f"  ok  {message}")


def api(path: str, method: str = "GET") -> Any:
    request = urllib.request.Request(f"{BASE_URL}{path}", method=method)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def new_page(browser) -> tuple[Page, list[str]]:
    page = browser.new_page(viewport={"width": 1280, "height": 1000})
    page.add_init_script(FAKE_MIDI)
    errors: list[str] = []
    page.on("console", lambda message: errors.append(f"{message.type}: {message.text}")
            if message.type == "error" else None)
    page.on("pageerror", lambda error: errors.append(f"pageerror: {error}"))
    # A missing favicon is not a defect; a missing bundle or API route is.
    page.on(
        "response",
        lambda response: errors.append(f"http {response.status}: {response.url}")
        if response.status >= 400 and not response.url.endswith("/favicon.ico")
        else None,
    )
    return page, errors


def click_button(page: Page, label: str, timeout: float = 20_000) -> None:
    """Click a button by its exact accessible name.

    ``text=Start`` is a substring match and can land on a neighbouring control
    in a row of buttons, so match the accessible name exactly instead.
    """
    page.get_by_role("button", name=label, exact=True).first.click(timeout=timeout)


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

    # Simulated device should be discovered and auto-selected.
    click_button(page, "Connect MIDI")
    page.wait_for_selector("text=MIDI connected", timeout=10_000)
    check(page.evaluate("() => window.__fakeMidi.ready()"), "app installed a MIDI message handler")

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
    badge = page.inner_text(".pill.accent").strip()
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
    check(True, "wrong pitches highlighted live in practice mode")
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
    check(page.evaluate("() => document.querySelectorAll('svg .area').length") == 1, "radar chart drawn")
    page.screenshot(path=str(SHOTS / "04-progress.png"), full_page=True)

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
            scenario_perfect(browser)
            scenario_wrong_and_silence(browser)
            scenario_calibration_and_stats(browser)
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
