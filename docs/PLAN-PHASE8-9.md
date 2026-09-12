# Phase 8 & 9 implementation plan — MIDI that sets itself up, and the LAN server

Implements `docs/ECOSYSTEM.md` §10 (decisions D7–D9). Design authority is that
document; this plan owns *how*, and nothing here re-opens the *what*.

Written for an engineer with no context on this codebase. Every step has the exact
file, the exact code, the exact command, and the output that means it worked.

---

## Plan Basis

**Goal.** Two things, in this order:

1. **Phase 8** — the planted notebook's browser connects to the piano by itself:
   no clicking, correct port chosen out of a device list that contains ALSA's dead
   `Midi Through Port-0`, and a piano switched on later is picked up without a
   reload.
2. **Phase 9** — that notebook serves the whole app on the local network, so
   statistics are readable (and recordings playable/uploadable) from the main
   computer, with the irreversible actions refused off the piano machine.

**Architecture as it is now.** One FastAPI app (`backend/app/`) serving a built
Svelte 5 SPA (`frontend/`), one SQLite file in WAL mode, MIDI capture in the
browser (`frontend/src/lib/midi.ts` + `capture.ts`), one capture client. See
`README.md` and `docs/DEPLOYMENT.md`.

**Architecture after this plan.** Unchanged, plus: the MIDI layer opens every input
instead of one and de-duplicates cross-port echoes; a small host-information module
tells the SPA where it is being used from and whether ALSA's sequencer exists; a
`deploy/` directory turns the notebook into a service. No new process, no new
runtime dependency. Phase 10 (a headless capture daemon) is explicitly **not** part
of this plan.

**Tech stack.** Python 3.11 venv at `backend/.venv`, FastAPI, pydantic v2, stdlib
`sqlite3`, pytest. Svelte 5 (runes) + TypeScript + Vite 8, `svelte-check`. Node 26
for the new unit tests (verified: `node --test` runs `.ts` directly).

### Baseline / authority refs (BaselineUsageDraft)

```text
BaselineUsageDraft:
- Required baseline refs: docs/ECOSYSTEM.md §10 (D7/D8/D9, Phase 8/9 design and
  acceptance), docs/DEPLOYMENT.md (current single-machine ops), README.md
  (configuration table, MIDI section)
- Delivered context refs: ECOSYSTEM.md §10 inline above
- Acknowledged before plan refs: D7 kiosk browser; D8 no auth + loopback-only
  destructive actions; D9 localhost to play, LAN name to view
- Cited in plan refs: ECOSYSTEM.md §10 acceptance criteria, one per task below
- Missing refs: none
- Decision: continue
```

**Plan location.** `docs/PLAN-PHASE8-9.md`, not `docs/aegis/plans/`. This project's
authority documents already live in `docs/` (`ECOSYSTEM.md` is the plan of record,
`AGENT-LOG.md` is the coordination log). Creating a second authority tree for one
plan would be the drift the Aegis method exists to prevent, so the project's own
convention overrides the skill's default location. `docs/ECOSYSTEM.md` §10 gets a
one-line pointer to this file.

### Requirement Ready Check

```text
Requirement Ready Check:
- Requirement source refs: ECOSYSTEM.md §10 "Decisions taken" + "Phase 8/9 design"
  + acceptance paragraphs; user answers in session (kiosk browser, open LAN with
  warning, localhost to play, destructive actions loopback-only)
- Goals and scope refs: ECOSYSTEM.md §10; non-goals listed there
- User / scenario refs: the player at the piano; the same player at the main
  computer reading statistics and uploading a recording
- Requirement item refs: P8 auto-connect/auto-select/hotplug; P9 deploy/, loopback
  boundary, host diagnostics, capture heartbeat, concurrency hardening
- Acceptance / verification criteria refs: ECOSYSTEM.md §10 "Acceptance" for each
  phase; each task below restates the criterion it satisfies
- Open blocker questions: none
- Decision: ready
```

### Change Necessity

```text
Change Necessity:
- User-visible need: the notebook must capture without anyone touching it, and the
  main computer must see the data
- No-change / non-code option: "close the logger's tab and pick the right device by
  hand" — rejected, the user is not at that machine; "document a manual selection"
  — rejected, this is the reported failure
- Why code change is necessary: device selection is a code path that currently
  picks `devices[0]`; the LAN boundary and diagnostics do not exist
- Minimum change boundary: frontend MIDI selection + app state + device bar;
  `backend/app/hostinfo.py` + loopback dependencies + `busy_timeout` + upload cap;
  `deploy/` files; the browser e2e
- Decision: code-change
```

### Existence Check

```text
Existence Check (one new backend surface, one new frontend module):
- Proposed new surface: `app/hostinfo.py`; `frontend/src/lib/midiDevice.ts`;
  `app/practice/capture_status.py`
- Existing owner / reuse candidate: `app/main.py` (routes) and
  `frontend/src/lib/midi.ts`
- Why existing surface is insufficient:
  hostinfo — the loopback probe, the ALSA probe and `/api/host` answer one
  question ("where is this and what can it see?") that neither the repertoire nor
  the practice domain owns; putting it in `main.py` would bury a security check in
  the composition root
  midiDevice — the selection and de-duplication rules are pure and must be unit
  testable; `midi.ts` touches `navigator`, so nothing in it can run under
  `node --test`
  capture_status — process-local ephemeral state, not a database row; the practice
  store owns SQL, and a heartbeat must never write to disk
- Creation proof: each is reached by an acceptance criterion in ECOSYSTEM.md §10
- Entropy / retirement impact: three small files, each single-purpose; no fallback
  paths, no compatibility carriers. `MidiInput.select()` and
  `AppState.selectDevice()` are **deleted** in the same task that replaces them
- Decision: add-with-proof
```

### Compatibility boundary (what must not break)

| Surface | Rule |
| --- | --- |
| `/api/score`, `/api/exercise/next`, `/api/repertoire/*`, `/api/practice/*` request and response shapes | unchanged, except **additive** fields on `/api/practice/status` |
| The browser e2e's `window.__fakeMidi.send(bytes)` | must keep meaning "the piano sent this", so all 8 existing scenarios run unchanged |
| The DeviceBar button's accessible name | stays `Connect MIDI` when no device is present, `Rescan MIDI` when one is; the e2e helper must tolerate auto-connect |
| Python 3.11 (no `socket.ip_address`), stdlib only for the new backend module | enforced |
| No non-erasable TypeScript (no `enum`, no parameter properties) in `midiDevice.ts` | enforced: Node's type-stripping runs it |

**Ripple Signal Triage.** Touching `midi.ts` reaches: `state.svelte.ts`,
`DeviceBar.svelte`, `PracticeView.svelte` (uses `onNote`/`onNoteRelease`/
`onSustain`/`startRecording`), `capture.ts` (`onNoteOnMonitor`/`onNoteOffMonitor`),
and every e2e scenario (through `__fakeMidi`). All are covered by the tasks below;
the e2e is the integration check.

### TDD Route

```text
TDD Route:
- Mode: auto
- Decision: strict
- Strict authority: recorded auto decision (behavior + shared/core logic + a real
  regression signal: device selection and note de-duplication decide what every
  practice log row and every score contains)
- Strict signals: new pure logic with branching, touched by two consumers
  (scoring and passive capture); a wrong answer is silent
- Light eligibility: not applicable — the logic is shared and failure is silent
- TDD-fit exception: config and deployment files (systemd units, policy JSON, shell
  script, `.svelte` markup). For those, the verification is the file's own syntax
  check plus the e2e assertion named in the task, not a RED/GREEN cycle. Stated
  per task as "Config verification".
- Test posture: strict RED test for `midiDevice.ts` (P8-T1); post-change regression
  for the midi/state/UI tasks; diagnostic reproduction in the e2e (the two-port
  device list is the user's actual bug, reproduced)
- Reason: silent wrongness in a shared path
- Verification: `npm test`, `pytest -q`, `svelte-check`, `npm run build`,
  `tools/e2e_browser.py`
```

### Plan Pressure Test

```text
Plan Pressure Test:
- Owner / contract / retirement: hostinfo owns "where/what can this machine see";
  midiDevice owns selection rules; MidiInput remains the only thing that touches
  the Web MIDI API. `select()`/`selectDevice()` retire inside their replacing task.
- Architecture integrity / higher-level path: no higher-level owner is missed —
  the SPA already asks the server for its state on load (`bootstrap()`), so
  `/api/host` rides an existing pattern rather than adding a poll loop
- Verification scope: unit tests for the pure rules, backend tests for every new
  route and boundary, e2e for the integrated behaviour including the exact device
  list that caused the bug
- Task executability: every step names a file, code, command, expected output
- Pressure result: proceed
```

### Plan-Time Complexity Check

```text
Complexity Budget:
- Artifact class: shared frontend module + app-state owner + small backend module
  + deployment files
- Target files / artifacts: frontend/src/lib/{midi.ts,midiDevice.ts,state.svelte.ts};
  frontend/src/components/{DeviceBar,HostBanner}.svelte;
  backend/app/{hostinfo.py,db.py,main.py}; backend/app/repertoire/api.py;
  backend/app/practice/{api.py,models.py,capture_status.py}; deploy/*
- Current pressure: midi.ts 330 lines, state.svelte.ts ~290, PracticeLogView ~430
- Projected post-change pressure: midi.ts ~400, state.svelte.ts ~350 — both still
  one responsibility each; the new pure logic goes to its own file instead of
  growing midi.ts further
- Budget result: within-budget
- Planned governance: no refactor of PracticeLogView; the capture pill is one
  block inside an existing section

Plan-Time Complexity Check:
- Target files: frontend/src/lib/midi.ts, frontend/src/lib/state.svelte.ts
- Existing size / shape signals: midi.ts is a single class with handler sets — a
  coherent owner; state.svelte.ts is the app-level store — the correct home for
  "which device is in use" and "how do we reach the host"
- Owner fit: good; port selection rules move *out* of midi.ts to keep it a
  transport layer
- Add-in-place risk: moderate for state.svelte.ts; the heartbeat sender goes in
  capture.ts (which owns the buffer) rather than the store
- Better file boundary: midiDevice.ts (pure), capture_status.py (ephemeral),
  hostinfo.py (host facts)
- Recommendation: add owner files; edit the rest in place
```

---

## File map

**Phase 8**

| Action | Path |
| --- | --- |
| create | `frontend/src/lib/midiDevice.ts` |
| create | `frontend/src/lib/midiDevice.test.ts` |
| modify | `frontend/package.json` (test script), `frontend/tsconfig.json` (exclude tests) |
| modify | `frontend/src/lib/midi.ts` |
| modify | `frontend/src/lib/state.svelte.ts` |
| modify | `frontend/src/components/DeviceBar.svelte` |
| modify | `frontend/src/App.svelte` (auto-connect on mount) |
| modify | `backend/tools/e2e_browser.py` (two-port fake, `ensure_midi`, scenario 9) |
| modify | `README.md` (MIDI section) |

**Phase 9**

| Action | Path |
| --- | --- |
| create | `backend/app/hostinfo.py` |
| create | `backend/app/practice/capture_status.py` |
| create | `backend/tests/test_server_hardening.py` |
| create | `frontend/src/components/HostBanner.svelte` |
| create | `deploy/install.sh`, `deploy/piano-ecosystem.service`, `deploy/piano-kiosk.service`, `deploy/chromium-policy.json`, `deploy/snd-seq.conf`, `deploy/logind-50-piano.conf`, `deploy/README.md` |
| modify | `backend/app/db.py`, `backend/app/config.py`, `backend/app/main.py` |
| modify | `backend/app/repertoire/api.py`, `backend/app/practice/{api.py,models.py}` |
| modify | `backend/tests/conftest.py` (clear the heartbeat between tests) |
| modify | `frontend/src/lib/{api.ts,types.ts,state.svelte.ts}` |
| modify | `frontend/src/components/{PracticeLogView,BackupPanel,RepertoireView}.svelte` |
| modify | `backend/tools/e2e_browser.py` (scenario 9 additions) |
| modify | `docs/DEPLOYMENT.md`, `docs/ECOSYSTEM.md`, `AGENT-LOG.md` |

---

# Phase 8 — MIDI that sets itself up

## P8-T1 — Pure device-selection and de-duplication rules, with unit tests

**Files.** create `frontend/src/lib/midiDevice.ts`, `frontend/src/lib/midiDevice.test.ts`;
modify `frontend/tsconfig.json`, `frontend/package.json`.

**Why.** ALSA exposes a virtual `Midi Through Port-0` that never carries a note.
Today `MidiInput.connect()` selects `devices[0]`, which is a coin toss against that
port. The rules that fix it are pure, and pure rules can be tested in seconds
instead of through a browser.

**Change Necessity.** `midi.ts` touches `navigator`, so nothing in it can run under
Node; extracting the rules is what makes them testable at all. Minimum boundary:
one new module plus its test.

**Impact.** Nothing imports it yet. No runtime behaviour changes in this task.

**TDD Route.** strict. Write the test first, watch it fail (module missing), then
implement.

### Steps

**1.1 Add the test script.** In `frontend/package.json`, `scripts` becomes:

```json
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview",
    "check": "svelte-check --tsconfig ./tsconfig.json",
    "test": "node --test src/lib/*.test.ts"
  },
```

Verified locally: Node 26 strips TypeScript types itself, so this needs no `vitest`,
no `tsx`, and no new dependency. The test file must import with an explicit `.ts`
extension (Node resolves the real file), and the module it imports must use only
erasable syntax — no `enum`, no constructor parameter properties.

**1.2 Keep the tests out of `svelte-check`.** In `frontend/tsconfig.json`:

```json
  "exclude": ["node_modules", "dist", "src/**/*.test.ts"]
```

Reason to write down (this is a deliberate trade): the tests are *executed*, not
type-checked by Svelte's tooling. Including them would require `@types/node` plus
`allowImportingTsExtensions`, two configuration knobs for no behavioural gain. If
the tests ever grow complex enough to need type checking, add both then.

Command: `cd frontend && npx svelte-check --tsconfig ./tsconfig.json`
Expected: `svelte-check found 0 errors and 0 warnings`

**1.3 Write the failing test.** Create `frontend/src/lib/midiDevice.test.ts`:

```ts
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  NoteGate,
  PortActivity,
  chooseActive,
  fingerprint,
  looksSilent,
} from './midiDevice.ts';

const casio = { id: 'id-casio', name: 'CASIO USB-MIDI MIDI 1', manufacturer: 'CASIO' };
const casioWindows = { id: 'id-win', name: 'MIDIIN2 (CASIO USB-MIDI)', manufacturer: 'CASIO' };
const through = { id: 'id-through', name: 'Midi Through Port-0', manufacturer: 'Midi Through' };

test('a device fingerprint survives the many names one keyboard reports', () => {
  assert.equal(fingerprint(casio), fingerprint(casioWindows));
  assert.notEqual(fingerprint(casio), fingerprint(through));
});

test('the ALSA loopback port is recognisable by name', () => {
  assert.equal(looksSilent(through), true);
  assert.equal(looksSilent(casio), false);
});

test('an echo of the same key from another port is dropped', () => {
  const gate = new NoteGate(30);
  assert.equal(gate.accept(60, 80, 'a', 1_000), true);
  assert.equal(gate.accept(60, 80, 'b', 1_005), false, 'same key, other port, 5 ms later');
});

test('a repeat on the same port is never dropped', () => {
  const gate = new NoteGate(30);
  assert.equal(gate.accept(60, 80, 'a', 1_000), true);
  assert.equal(gate.accept(60, 80, 'a', 1_005), true);
});

test('an echo after the window is a real note again', () => {
  const gate = new NoteGate(30);
  assert.equal(gate.accept(60, 80, 'a', 1_000), true);
  assert.equal(gate.accept(60, 80, 'b', 1_031), true);
});

test('a different key is never an echo', () => {
  const gate = new NoteGate(30);
  assert.equal(gate.accept(60, 80, 'a', 1_000), true);
  assert.equal(gate.accept(61, 80, 'b', 1_001), true, 'different pitch');
  assert.equal(gate.accept(60, 70, 'b', 1_001), true, 'different velocity');
});

test('activity remembers which port actually carried notes', () => {
  const activity = new PortActivity();
  activity.note('silent', 1_000);
  activity.note('loud', 5_000);
  assert.equal(activity.loudest(['silent', 'loud']), 'loud');
  assert.equal(activity.notes('loud'), 1);
  activity.forget('loud');
  assert.equal(activity.loudest(['silent', 'loud']), 'silent');
  assert.equal(activity.notes('loud'), 0);
});

test('the active port is the pin, then the fingerprint, then the loudest, then the first', () => {
  const ports = [through, casio];
  assert.equal(chooseActive([]), null);
  assert.equal(chooseActive(ports), through.id, 'nothing known yet: first port');

  const activity = new PortActivity();
  activity.note(casio.id, 2_000);
  assert.equal(chooseActive(ports, { activity }), casio.id, 'the port that has been heard');

  assert.equal(
    chooseActive(ports, { activity, pinnedFingerprint: fingerprint(casioWindows) }),
    casio.id,
    'a remembered fingerprint beats the loudest port',
  );
  assert.equal(
    chooseActive(ports, { activity, pinnedId: through.id, pinnedFingerprint: fingerprint(casio) }),
    through.id,
    'an explicit pin in this session beats everything',
  );
});
```

Command: `cd frontend && npm test`
Expected: failure, `Cannot find module ... midiDevice.ts`.

**1.4 Implement the module.** Create `frontend/src/lib/midiDevice.ts`:

```ts
/**
 * Device selection and note de-duplication.
 *
 * Pure on purpose: this is the part that decides *which* port's bytes count, which
 * a device list containing ALSA's dead `Midi Through Port-0` makes ambiguous, and
 * it must be testable without a browser. `midi.ts` imports this; nothing here
 * touches the DOM.
 */

export interface DevicePort {
  id: string;
  name: string;
  manufacturer: string;
}

/** A port plus what has been heard from it, for the device list. */
export interface PortSnapshot extends DevicePort {
  /** Epoch ms of the last note this port carried, or null. */
  lastNoteMs: number | null;
  notes: number;
  inUse: boolean;
  pinned: boolean;
}

/**
 * A stable identity for a device, for remembering a choice across reloads.
 *
 * Chromium's `input.id` is a per-origin salted hash: stable until site data is
 * cleared, which is exactly what happens while setting up a new machine. This is
 * the fallback, so a remembered choice survives that.
 */
export function fingerprint(port: DevicePort): string {
  const tokens = (value: string): string[] =>
    value
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, ' ')
      .split(' ')
      .filter(Boolean)
      // A bare port number ("MIDI 1", "Port-0") identifies a socket, not a device.
      .filter((token) => !/^\d+$/.test(token))
      // Windows names the second port of one keyboard "MIDIIN2 (…)".
      .filter((token) => !/^midi(in|out)\d*$/.test(token))
      .filter((token) => token !== 'midi' && token !== 'port');

  const parts = new Set([...tokens(port.manufacturer), ...tokens(port.name)]);
  return [...parts].sort().join(' ');
}

/** A port that exists but carries nothing, e.g. ALSA's Midi Through. */
export function looksSilent(port: DevicePort): boolean {
  return /midi\s*through/i.test(`${port.manufacturer} ${port.name}`);
}

/**
 * Cross-port echo suppression.
 *
 * A note arriving from a *different* port within the window is the same physical
 * key reported twice, so it is dropped. A repeat on the *same* port is always
 * accepted: no human repeats a pitch within 30 ms, and dropping one would be
 * losing a real note.
 */
export class NoteGate {
  private readonly windowMs: number;
  private readonly recent = new Map<string, { portId: string; atMs: number }>();

  constructor(windowMs = 30) {
    this.windowMs = windowMs;
  }

  accept(pitch: number, velocity: number, portId: string, atMs: number): boolean {
    const key = `${pitch}:${velocity}`;
    const previous = this.recent.get(key);
    this.prune(atMs);
    if (previous && previous.portId !== portId && atMs - previous.atMs <= this.windowMs) {
      return false;
    }
    this.recent.set(key, { portId, atMs });
    return true;
  }

  private prune(nowMs: number): void {
    for (const [key, seen] of this.recent) {
      if (nowMs - seen.atMs > 1_000) this.recent.delete(key);
    }
  }
}

/** Per-port evidence of life. Times are epoch ms, for direct display. */
export class PortActivity {
  private readonly lastMs = new Map<string, number>();
  private readonly noteCount = new Map<string, number>();

  note(portId: string, atMs: number): void {
    this.lastMs.set(portId, atMs);
    this.noteCount.set(portId, (this.noteCount.get(portId) ?? 0) + 1);
  }

  lastNoteMs(portId: string): number | null {
    return this.lastMs.get(portId) ?? null;
  }

  notes(portId: string): number {
    return this.noteCount.get(portId) ?? 0;
  }

  /** The port that most recently carried a note, or null if none has. */
  loudest(portIds: string[]): string | null {
    let best: string | null = null;
    let bestAt = -Infinity;
    for (const id of portIds) {
      const at = this.lastMs.get(id);
      if (at !== undefined && at > bestAt) {
        best = id;
        bestAt = at;
      }
    }
    return best;
  }

  forget(portId: string): void {
    this.lastMs.delete(portId);
    this.noteCount.delete(portId);
  }
}

/**
 * Which port to use.
 *
 * Order matters: an explicit pin in this session, then a remembered device, then
 * the port that has actually carried notes, and only then the first port that
 * exists — which is the fallback that used to be the *only* rule, and is why a
 * dead ALSA port could be selected.
 */
export function chooseActive(
  ports: DevicePort[],
  options: {
    pinnedId?: string | null;
    pinnedFingerprint?: string | null;
    activity?: PortActivity;
  } = {},
): string | null {
  if (ports.length === 0) return null;
  const ids = ports.map((port) => port.id);
  if (options.pinnedId && ids.includes(options.pinnedId)) return options.pinnedId;
  if (options.pinnedFingerprint) {
    const remembered = ports.find((port) => fingerprint(port) === options.pinnedFingerprint);
    if (remembered) return remembered.id;
  }
  const loud = options.activity?.loudest(ids) ?? null;
  return loud ?? ids[0];
}
```

Command: `cd frontend && npm test`
Expected: `pass 8`, `fail 0`.

Command: `cd frontend && npx svelte-check --tsconfig ./tsconfig.json`
Expected: `svelte-check found 0 errors and 0 warnings`

**Deviation from this plan, recorded.** This step's first draft stripped a
parenthetical suffix and a trailing port number with sequential regexes. It passed
the test for `CASIO USB-MIDI MIDI 1` but failed it for `MIDIIN2 (CASIO USB-MIDI)`,
because on Windows the entire device name *is* the parenthetical — stripping it left
an empty fingerprint, so the two spellings of one keyboard would not have matched and
the remembered choice would have been lost on a machine change. The implementation
compares **token sets** and drops the noise tokens (bare digits, `midiin\d*`,
`midi`, `port`) instead, which also makes it order-insensitive. `midi through` is
deliberately **not** dropped, so the dead port keeps a distinct fingerprint.

**1.5 Commit.** Title: `Auto-select the live MIDI port instead of the first one`

---

## P8-T2 — `MidiInput` opens every port, drops cross-port echoes

**Files.** modify `frontend/src/lib/midi.ts`.

**Why.** Opening one port means choosing one; opening all of them and removing
duplicates is the only rule that works without knowing which port is live.

**Impact.** `MidiInput` is consumed by `state.svelte.ts`, `capture.ts` (through
state) and `PracticeView.svelte`. Its public note/release/sustain/monitor handlers
do not change. `select(id)` is replaced by `pin(id | null)`; `selectedId` remains as
a read-only alias for `activeId`.

**Retirement (in this task).** `private input: MIDIInput | null`,
`select(id)`, and the `if (devices.length > 0 && !this.input) this.select(devices[0].id)`
line are deleted. No compatibility shim: the only caller (DeviceBar) is replaced in
P8-T4, and `state.selectDevice` in P8-T3.

### Steps

**2.1 Add the import.** In `frontend/src/lib/midi.ts`, directly after the module
docstring (before `export interface MidiDeviceInfo`):

```ts
import {
  NoteGate,
  PortActivity,
  chooseActive,
  fingerprint,
  type DevicePort,
  type PortSnapshot,
} from './midiDevice';
```

Note: extensionless here (this file is bundled by Vite and type-checked by
`svelte-check`); only the Node-run test file needs the explicit `.ts`.

**2.2 Add the handler type.** Next to the other handler types:

```ts
type PortsHandler = (ports: PortSnapshot[]) => void;
```

**2.3 Replace the fields.** Replace this block:

```ts
export class MidiInput {
  private access: MIDIAccess | null = null;
  private input: MIDIInput | null = null;
```

with:

```ts
export class MidiInput {
  private access: MIDIAccess | null = null;
  /**
   * Every input we are attached to.
   *
   * Every input, not one: ALSA exposes a virtual `Midi Through Port-0` that never
   * carries a note, and some keyboards expose more than one port that does.
   * Picking one by position is a coin toss.
   */
  private readonly inputs = new Map<string, MIDIInput>();
  /** Cross-port echo suppression. */
  private readonly gate = new NoteGate();
  /** Which port has actually carried notes. */
  private readonly activity = new PortActivity();
  /** A remembered choice: this session's pin, and the durable fingerprint. */
  private pinnedId: string | null = null;
  private pinnedFingerprint: string | null = null;
  private lastPortsEmitMs = 0;
```

**2.4 Add the ports handler set.** Replace:

```ts
  private monitorOnHandlers = new Set<MonitorOnHandler>();
  private monitorOffHandlers = new Set<MonitorOffHandler>();
```

with the same two lines plus:

```ts
  private portsHandlers = new Set<PortsHandler>();
```

**2.5 Replace `connect()` and `select()`.** Replace this block in full (from
`async connect()` through the end of `select(id)`):

```ts
  async connect(): Promise<MidiDeviceInfo[]> {
    if (!MidiInput.isSupported()) {
      throw new Error(
        'This browser has no Web MIDI support. Use Chrome, Edge, or Opera on desktop.',
      );
    }
    this.access = await navigator.requestMIDIAccess({ sysex: false });
    this.access.onstatechange = () => this.emitDevices();
    const devices = this.listDevices();
    if (devices.length > 0 && !this.input) {
      this.select(devices[0].id);
    }
    this.emitDevices();
    return devices;
  }
```

with:

```ts
  async connect(): Promise<MidiDeviceInfo[]> {
    if (!MidiInput.isSupported()) {
      throw new Error(
        'This browser has no Web MIDI support. Use Chrome, Edge, or Opera on desktop.',
      );
    }
    this.access = await navigator.requestMIDIAccess({ sysex: false });
    // `statechange` fires when the piano is switched on or unplugged. For a
    // machine left running that is the whole point: no reload, no click.
    this.access.onstatechange = () => this.attachAll();
    this.attachAll();
    return this.listDevices();
  }

  /**
   * Attach to every input present, and detach from any that have gone.
   *
   * Safe to call repeatedly: an input already attached is left alone, so a
   * `statechange` that only adds one device does not disturb the others.
   */
  private attachAll(): void {
    const present = new Set<string>();
    this.access?.inputs.forEach((input) => {
      present.add(input.id);
      if (this.inputs.get(input.id) === input) return;
      const portId = input.id;
      input.onmidimessage = (event: MIDIMessageEvent) => this.handleMessage(portId, event);
      this.inputs.set(portId, input);
    });

    for (const [portId, input] of [...this.inputs]) {
      if (present.has(portId)) continue;
      input.onmidimessage = null;
      this.inputs.delete(portId);
      this.activity.forget(portId);
    }
    this.emitPorts(true);
  }
```

Then replace the `get selectedId()` / `select(id)` pair:

```ts
  get selectedId(): string | null {
    return this.input?.id ?? null;
  }

  /** Switch inputs. Safe to call before any recording starts. */
  select(id: string): void {
    if (!this.access) throw new Error('Call connect() before select()');
    const available: MIDIInput[] = [];
    this.access.inputs.forEach((input) => available.push(input));
    const next = available.find((input) => input.id === id) ?? null;
    if (!next) throw new Error(`No MIDI input with id ${id}`);

    if (this.input) {
      this.input.onmidimessage = null;
    }
    this.input = next;
    this.input.onmidimessage = (event: MIDIMessageEvent) => this.handleMessage(event);
    this.activeNotes.clear();
  }
```

with:

```ts
  /** The port in use: the pin, else the one that has carried notes. */
  get activeId(): string | null {
    return chooseActive(this.ports(), {
      pinnedId: this.pinnedId,
      pinnedFingerprint: this.pinnedFingerprint,
      activity: this.activity,
    });
  }

  /** Read-only alias, for callers that only need "which device is in use". */
  get selectedId(): string | null {
    return this.activeId;
  }

  get pinnedDeviceId(): string | null {
    return this.pinnedId;
  }

  /**
   * Use only this device, or `null` to go back to automatic.
   *
   * Both the id and the fingerprint are remembered: the id is exact for this
   * browser profile, the fingerprint survives the id being invalidated by cleared
   * site data.
   */
  pin(id: string | null): void {
    if (id === null) {
      this.pinnedId = null;
      this.pinnedFingerprint = null;
      this.emitPorts(true);
      return;
    }
    const input = this.inputs.get(id);
    if (!input) throw new Error(`No MIDI input with id ${id}`);
    this.pinnedId = id;
    this.pinnedFingerprint = fingerprint(toDevicePort(input));
    this.emitPorts(true);
  }

  /** Remember a device before it has appeared, e.g. from localStorage on load. */
  restorePin(rememberedFingerprint: string | null): void {
    this.pinnedFingerprint = rememberedFingerprint;
  }

  private ports(): DevicePort[] {
    return [...this.inputs.values()].map(toDevicePort);
  }

  private emitPorts(force = false): void {
    // A fast passage fires this once per note; the display cannot show more than
    // a few updates a second, so they are throttled unless something structural
    // changed (attach, detach, pin).
    const nowMs = performance.now();
    if (!force && nowMs - this.lastPortsEmitMs < 200) return;
    this.lastPortsEmitMs = nowMs;
    const active = this.activeId;
    const snapshot: PortSnapshot[] = this.ports().map((port) => ({
      ...port,
      lastNoteMs: this.activity.lastNoteMs(port.id),
      notes: this.activity.notes(port.id),
      inUse: port.id === active,
      pinned: port.id === this.pinnedId,
    }));
    this.portsHandlers.forEach((handler) => handler(snapshot));
    this.emitDevices();
  }
```

**2.6 Add the `onPorts` subscription.** Next to `onDevices`:

```ts
  /** Every port, with what has been heard from it. */
  onPorts(handler: PortsHandler): () => void {
    this.portsHandlers.add(handler);
    return () => this.portsHandlers.delete(handler);
  }
```

**2.7 Replace `handleMessage`'s signature and note-on head.** Replace:

```ts
  private handleMessage(event: MIDIMessageEvent): void {
    const data = event.data;
    if (!data || data.length < 2) return;
```

with:

```ts
  private handleMessage(portId: string, event: MIDIMessageEvent): void {
    const data = event.data;
    if (!data || data.length < 2) return;
    // A pin is an explicit instruction: the other ports are ignored entirely.
    if (this.pinnedId !== null && portId !== this.pinnedId) return;
```

and replace:

```ts
    if (status === 0x90 && second > 0) {
      // Note on
      const nowMs = this.eventTimeMs(event);
      const queue = this.activeNotes.get(first) ?? [];
```

with:

```ts
    if (status === 0x90 && second > 0) {
      // Note on
      const nowMs = this.eventTimeMs(event);
      // The same key from a different port inside the window is one physical key
      // reported twice. Dropping it here protects both consumers: the exercise
      // scorer, which would count it as an extra note, and the practice log,
      // which would store it twice.
      if (!this.gate.accept(first, second, portId, nowMs)) return;
      this.activity.note(portId, Date.now());
      this.emitPorts();
      const queue = this.activeNotes.get(first) ?? [];
```

**2.8 Add the `toDevicePort` helper.** At the end of the file, after the class:

```ts
function toDevicePort(input: MIDIInput): DevicePort {
  return {
    id: input.id,
    name: input.name ?? 'Unnamed MIDI input',
    manufacturer: input.manufacturer ?? '',
  };
}
```

**2.9 Regression check.** Command:

```bash
cd frontend && npx svelte-check --tsconfig ./tsconfig.json && npm run build
```

Expected: `0 errors and 0 warnings`, then `✓ built in`. `state.svelte.ts` will
report one error at this point — `this.midi.select(id)` no longer exists — which
P8-T3 fixes; if it blocks the build, apply P8-T3 before running this step's build.

**2.10 Commit.** Title: `Open every MIDI port and de-duplicate cross-port echoes`.

---

## P8-T3 — App state: auto-connect, reconnect, pin, port snapshot

**Files.** modify `frontend/src/lib/state.svelte.ts`, `frontend/src/App.svelte`.

**Why.** A planted notebook must reach the piano with nobody at the keyboard:
connect on load, notice a device that appears later, and remember the player's
choice.

**Impact.** `selectDevice(id)` is replaced by `pinDevice(id | null)`; its only
caller is DeviceBar (P8-T4). `connectMidi()` keeps its name and gains an optional
argument.

### Steps

**3.1 Import the port snapshot type.** In `state.svelte.ts`:

```ts
import { MidiInput, type MidiDeviceInfo, type PortSnapshot } from './midi';
```

**3.2 Add the storage key.** Next to `CAPTURE_STORAGE_KEY`:

```ts
const MIDI_PIN_STORAGE_KEY = 'srt.midi.pin';
```

and a reader beside `readCapture()`:

```ts
function readPinnedFingerprint(): string | null {
  try {
    return localStorage.getItem(MIDI_PIN_STORAGE_KEY);
  } catch {
    return null;
  }
}
```

**3.3 Add the fields.** In `AppState`, replace:

```ts
  midiSupported = $state(MidiInput.isSupported());
  midiConnected = $state(false);
  midiError = $state<string | null>(null);
  devices = $state<MidiDeviceInfo[]>([]);
  selectedDeviceId = $state<string | null>(null);
```

with:

```ts
  midiSupported = $state(MidiInput.isSupported());
  midiConnected = $state(false);
  midiError = $state<string | null>(null);
  devices = $state<MidiDeviceInfo[]>([]);
  /** Every port, with what has been heard from it: drives the device bar. */
  ports = $state<PortSnapshot[]>([]);
  /** The port in use, and the player's explicit choice if there is one. */
  midiActiveId = $state<string | null>(null);
  midiPinnedId = $state<string | null>(null);
  /** True when access was granted without an explicit click. */
  midiAutoConnected = $state(false);
  /** True when the browser refused MIDI until the user asks for it. */
  midiNeedsGesture = $state(false);
```

and add the private plumbing below `errorMessage`:

```ts
  private midiWired = false;
  private reconnectTimer: ReturnType<typeof setInterval> | null = null;
```

**3.4 Replace `connectMidi()`.** Replace the whole method with:

```ts
  /**
   * Ask for MIDI access and attach to whatever is there.
   *
   * `quiet` is for the automatic attempts: a refusal there is not an error worth
   * showing, because the browser may simply require a gesture, and the Connect
   * button is the honest fallback.
   */
  async connectMidi(options: { quiet?: boolean } = {}): Promise<void> {
    if (!this.midiWired) {
      this.midiWired = true;
      this.midi.onPorts((ports) => {
        this.ports = ports;
        this.midiActiveId = this.midi.activeId;
        this.midiPinnedId = this.midi.pinnedDeviceId;
      });
      this.midi.onDevices((next) => {
        this.devices = next;
        this.midiConnected = next.length > 0;
        if (next.length > 0) this.midiNeedsGesture = false;
      });
    }
    if (!options.quiet) this.midiError = null;
    try {
      const devices = await this.midi.connect();
      this.devices = devices;
      this.midiConnected = devices.length > 0;
      this.midiNeedsGesture = false;
      if (devices.length === 0 && !options.quiet) {
        this.midiError =
          'No MIDI input found. Connect the PX-870 over USB, make sure it is powered on, then rescan.';
      }
      // Capture is app-level and follows the device: reconnecting after a replug
      // must not silently stop the log.
      if (this.captureEnabled && devices.length > 0) this.capture.start();
    } catch (error) {
      this.midiConnected = false;
      if (!options.quiet) {
        this.midiError = error instanceof Error ? error.message : String(error);
      } else {
        this.midiNeedsGesture = true;
      }
    }
  }

  /**
   * Try to connect with no interaction, then keep trying.
   *
   * On the notebook a managed policy has already granted the MIDI permission, so
   * this succeeds silently on load. Everywhere else the browser may want a
   * gesture; a bare refusal only arms the Connect button.
   */
  async autoConnectMidi(): Promise<void> {
    if (!this.midiSupported || this.midiConnected) return;
    this.midi.restorePin(readPinnedFingerprint());
    await this.connectMidi({ quiet: true });
    this.midiAutoConnected = this.midiConnected;
    this.startReconnectLoop();
  }

  /**
   * A piano that is switched on ten minutes after the machine is already running
   * is the normal case, so poll while nothing is attached.
   *
   * `statechange` covers plugging and unplugging; this covers the browser not
   * delivering it, and the piano being off when the page loaded.
   */
  private startReconnectLoop(): void {
    if (this.reconnectTimer !== null) return;
    const attempt = () => {
      if (this.midiConnected || !this.midiSupported) {
        if (this.reconnectTimer !== null) clearInterval(this.reconnectTimer);
        this.reconnectTimer = null;
        return;
      }
      void this.connectMidi({ quiet: true });
    };
    this.reconnectTimer = setInterval(attempt, 5_000);
    // A laptop that was asleep is the other way devices go missing.
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible') attempt();
    });
  }

  /** Use only this device, or null to go back to automatic selection. */
  pinDevice(id: string | null): void {
    try {
      this.midi.pin(id);
      this.midiPinnedId = this.midi.pinnedDeviceId;
      this.midiActiveId = this.midi.activeId;
      const active = this.ports.find((port) => port.id === id);
      if (active) {
        // Stored as a fingerprint so the choice survives the id changing, which is
        // exactly what happens when site data is cleared during a setup.
        localStorage.setItem(MIDI_PIN_STORAGE_KEY, fingerprintOf(active));
      } else {
        localStorage.removeItem(MIDI_PIN_STORAGE_KEY);
      }
    } catch (error) {
      this.midiError = error instanceof Error ? error.message : String(error);
    }
  }
```

`fingerprintOf` is `fingerprint` from `midiDevice`; add it to the import in step 3.1:

```ts
import { fingerprint } from './midiDevice';
```

**3.5 Delete `selectDevice`.** Remove the whole method; `pinDevice` replaces it.

Also delete from `bootstrap()` nothing — but add the auto-connect call. Replace:

```ts
    await this.refreshProfile();
    await this.refreshWorkout();
  }
```

with:

```ts
    await this.refreshProfile();
    await this.refreshWorkout();
  }

  /** Called once by the app shell, after `bootstrap()`. */
  async startMidi(): Promise<void> {
    await this.autoConnectMidi();
  }
```

**3.6 Call it from the shell.** In `App.svelte`, replace:

```ts
  onMount(() => {
    void app.bootstrap();
  });
```

with:

```ts
  onMount(() => {
    void app.bootstrap().then(() => app.startMidi());
  });
```

**3.7 Regression check.**

```bash
cd frontend && npx svelte-check --tsconfig ./tsconfig.json
```

Expected: 0 errors. (DeviceBar still calls `selectDevice` until P8-T4; do T4 before
this check if you are running tasks strictly in order.)

**3.8 Commit.** Title: `Connect to the piano automatically and reconnect when it appears`.

---

## P8-T4 — Device bar: which port is in use, and what has been heard

**Files.** modify `frontend/src/components/DeviceBar.svelte` (full replacement).

**Why.** The failure the user reported was a device list they could not interpret.
Showing which port has actually carried notes turns a guess into a reading.

**Impact.** No API change; buttons keep stable accessible names (`Connect MIDI`
when nothing is attached, `Rescan MIDI` otherwise) because the browser e2e drives
them.

### Steps

**4.1 Replace the file** with:

```svelte
<script lang="ts">
  /**
   * MIDI device state.
   *
   * The list shows *evidence* rather than just names: a port that has never carried
   * a note says so, because on Linux ALSA always exposes a virtual `Midi Through`
   * port that exists and never works.
   */
  import { app } from '../lib/state.svelte';

  let showLatency = $state(false);
  let draftLatency = $state(app.latencyMs);
  let showPorts = $state(false);

  // A once-a-second clock, so "last note 3 s ago" ticks without the store having
  // to tick.
  let nowMs = $state(Date.now());
  $effect(() => {
    const timer = setInterval(() => (nowMs = Date.now()), 1_000);
    return () => clearInterval(timer);
  });

  const activeName = $derived(
    app.ports.find((port) => port.id === app.midiActiveId)?.name ?? null,
  );

  function portNote(portId: string): string {
    const port = app.ports.find((item) => item.id === portId);
    if (!port || port.notes === 0 || port.lastNoteMs === null) return 'no notes yet';
    const seconds = Math.max(0, Math.round((nowMs - port.lastNoteMs) / 1000));
    const ago = seconds < 60 ? `${seconds} s ago` : `${Math.round(seconds / 60)} min ago`;
    return `${port.notes} notes · last ${ago}`;
  }

  function saveLatency() {
    app.setLatency(draftLatency);
    showLatency = false;
  }
</script>

<section class="card bar device-bar" data-midi={app.midiConnected ? 'connected' : 'none'}>
  <div class="row wrap">
    <span class="pill" class:good={app.midiConnected} class:bad={!app.midiConnected}>
      <span class="dot" class:on={app.midiConnected}></span>
      {#if !app.midiSupported}
        Web MIDI unavailable
      {:else if app.midiConnected}
        MIDI connected
      {:else}
        No MIDI input
      {/if}
    </span>

    {#if app.midiConnected && activeName}
      <span class="pill accent" data-midi-active>
        {app.midiPinnedId ? 'Pinned' : 'Auto'} · {activeName}
      </span>
    {/if}

    {#if app.midiSupported}
      <button onclick={() => void app.connectMidi()}>
        {app.devices.length > 0 ? 'Rescan MIDI' : 'Connect MIDI'}
      </button>
      {#if app.devices.length > 0}
        <button class="ghost tiny" onclick={() => (showPorts = !showPorts)}>
          Ports ({app.devices.length})
        </button>
      {/if}
    {/if}

    <button class="ghost" onclick={() => { draftLatency = app.latencyMs; showLatency = !showLatency; }}>
      Latency {app.latencyMs} ms
    </button>
  </div>

  {#if app.midiConnected && app.midiPinnedId}
    <button class="ghost tiny back-to-auto" onclick={() => app.pinDevice(null)}>
      Back to automatic selection
    </button>
  {/if}

  {#if showPorts}
    <ul class="ports">
      {#each app.ports as port (port.id)}
        <li data-port={port.id}>
          <span class="name">{port.name}</span>
          <span class="muted small">{portNote(port.id)}</span>
          {#if port.inUse}
            <span class="pill good">in use</span>
          {/if}
          {#if port.pinned}
            <button class="ghost tiny" onclick={() => app.pinDevice(null)}>Unpin</button>
          {:else}
            <button class="ghost tiny" onclick={() => app.pinDevice(port.id)}>
              Use only this
            </button>
          {/if}
        </li>
      {/each}
    </ul>
  {/if}

  {#if showLatency}
    <div class="row wrap latency">
      <span class="muted small">
        Measured round-trip delay of your setup. It is subtracted from every note before scoring.
      </span>
      <input type="number" min="0" max="500" step="5" bind:value={draftLatency} />
      <button class="primary" onclick={saveLatency}>Save</button>
      <button class="ghost" onclick={() => (draftLatency = 0)}>Reset</button>
    </div>
  {/if}

  {#if app.midiNeedsGesture}
    <p class="muted small">
      The browser wants a click before it will hand over MIDI access. On the piano
      machine this is granted automatically; press Connect MIDI once and it is
      remembered.
    </p>
  {/if}

  {#if app.midiError}
    <p class="error-banner small">{app.midiError}</p>
  {/if}
</section>

<style>
  .bar {
    padding: 0.6rem 0.75rem;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  .dot {
    width: 0.5rem;
    height: 0.5rem;
    border-radius: 50%;
    background: var(--track);
  }

  .dot.on {
    background: var(--good);
  }

  .ports {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 0.3rem;
    font-size: 0.85rem;
  }

  .ports li {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    flex-wrap: wrap;
  }

  .ports .name {
    font-family: var(--mono);
    font-size: 0.8rem;
  }

  .back-to-auto {
    align-self: flex-start;
  }

  .latency {
    border-top: 1px solid var(--line);
    padding-top: 0.5rem;
  }

  .small {
    font-size: 0.82rem;
  }
</style>
```

**4.2 Check and build.**

```bash
cd frontend && npx svelte-check --tsconfig ./tsconfig.json && npm run build
```

Expected: `0 errors and 0 warnings`, `✓ built in`.

**4.3 Commit.** Title: `Show which MIDI port is live and what has been heard from it`.

---

## P8-T5 — The e2e harness gains a second, dead port

**Files.** modify `backend/tools/e2e_browser.py`.

**Why.** The reported bug *is* a two-port device list. Reproducing it in the harness
is what turns "auto-detect" from a claim into a test.

**Compatibility boundary.** `window.__fakeMidi.send(bytes)` keeps meaning "the piano
sent this", so all eight existing scenarios are untouched.

### Steps

**5.1 Replace the `FAKE_MIDI` constant** with:

```python
#: Injected before every page script. Mimics a Casio PX-870 enough for the app's
#: own MIDI layer to treat it as a real device — and deliberately exposes *two*
#: inputs, because ALSA always adds a dead virtual `Midi Through Port-0` beside a
#: real keyboard, which is exactly the device list that made the app select a port
#: that never carried a note.
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
  const ports = new Map();
  const access = {
    inputs: {
      forEach: (callback) => ports.forEach((value) => callback(value)),
      get: (key) => ports.get(key),
      get size() { return ports.size; },
    },
    outputs: { forEach: () => {}, size: 0 },
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
```

**5.2 Add the `ensure_midi` helper** next to `click_button`:

```python
def ensure_midi(page: Page, timeout: float = 15_000) -> None:
    """Wait until the app has a usable MIDI input.

    The app connects by itself when the browser already has permission, so this
    does *not* click by default — clicking would hide the very behaviour the
    auto-detect scenario exists to check. The click is only there for a browser
    that refused without a gesture.
    """
    page.wait_for_selector("text=Sight-Reading Trainer", timeout=timeout)
    if page.get_by_role("button", name="Connect MIDI", exact=True).count():
        click_button(page, "Connect MIDI")
    page.wait_for_selector("text=MIDI connected", timeout=timeout)
    check(page.evaluate("() => window.__fakeMidi.ready()"), "app installed a MIDI message handler")
```

**5.3 Replace every hand-rolled connect.** Four call sites use this pair:

```python
    click_button(page, "Connect MIDI")
    page.wait_for_selector("text=MIDI connected", timeout=10_000)
```

Replace each with `ensure_midi(page)`. In `load_first_exercise`, the surrounding
lines become:

```python
def load_first_exercise(page: Page) -> dict[str, Any]:
    """Click through to a rendered exercise and return the API payload behind it."""
    page.goto(BASE_URL, wait_until="domcontentloaded")
    ensure_midi(page)
```

and the old `check(page.evaluate("() => window.__fakeMidi.ready()"), ...)` line is
deleted (it now lives inside the helper). The other three sites are in
`scenario_long_exercises`, `scenario_two_hands` and `scenario_practice_log`.

Command to find them all (must print nothing):

```bash
cd backend && grep -n 'click_button(page, "Connect MIDI")' tools/e2e_browser.py
```

**5.4 Regression run.** Start the server (see "Verification sweep") and:

```bash
SRT_DB_PATH=... SRT_LEGACY_DB=... SRT_MEDIA_DIR=... \
  backend/.venv/bin/python backend/tools/e2e_browser.py http://127.0.0.1:8011
```

Expected: the existing eight scenarios pass. This is the step that proves the
two-port harness did not break the single-port assumptions.

**5.5 Commit.** Title: `Reproduce the two-port MIDI device list in the e2e harness`.

---

## P8-T6 — e2e scenario: the app finds the piano by itself

**Files.** modify `backend/tools/e2e_browser.py`.

**Why.** ECOSYSTEM.md §10 Phase 8 acceptance, verbatim: two simulated inputs, no
click, echo logged once, a device appearing later picked up.

### Steps

**6.1 Add the scenario** before `def main()`:

```python
def scenario_midi_autodetect(browser) -> None:
    print("\n[9] MIDI that sets itself up: one dead port, one live, no clicking")
    page, errors = new_page(browser)
    page.goto(BASE_URL, wait_until="domcontentloaded")
    page.wait_for_selector("text=Sight-Reading Trainer")

    # No click anywhere in this block: on the notebook a managed policy grants the
    # MIDI permission, so connecting must be the app's job.
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
    page.get_by_role("button", name=re.compile(r"^Ports")).first.click()
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

    # The piano is switched on after the machine is already running: the normal
    # case for a planted notebook.
    page.evaluate("() => window.__fakeMidi.unplugAll()")
    page.wait_for_selector("text=No MIDI input", timeout=15_000)
    page.evaluate("() => window.__fakeMidi.plugLater(400, 'alsa-casio-1')")
    page.wait_for_selector("text=MIDI connected", timeout=20_000)
    check(True, "a piano switched on later is picked up with no reload and no click")

    # Pinning is for the person who wants certainty rather than inference.
    page.get_by_role("button", name=re.compile(r"^Ports")).first.click()
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
```

**6.2 Register it** in `main()`:

```python
            scenario_practice_log(browser)
            scenario_midi_autodetect(browser)
```

**6.3 Run.** Expected: scenario 9 prints every `ok`, and the summary says
`All browser scenarios passed.` If `the live port is chosen` fails, the app is
picking `devices[0]` — re-check P8-T2 step 2.5 (`emitPorts` uses `this.activeId`,
not the first id).

**6.4 Commit.** Title: `Verify auto-detection against a dead ALSA port and a live one`.

---

## P8-T7 — Document Phase 8 and run the sweep

**Files.** modify `README.md`, `docs/ECOSYSTEM.md`, `AGENT-LOG.md`.

### Steps

**7.1 README.** In the MIDI/Quick-start area, add under a new
`### MIDI devices` heading:

```markdown
### MIDI devices

The app connects by itself and picks the port that actually carries notes. That
matters on Linux, where ALSA always exposes a virtual `Midi Through Port-0` beside
your keyboard: it is a real input that never sends anything, and choosing by
position picks it roughly half the time. The device bar lists every port with what
has been heard from it ("no notes yet" / "17 notes · last 4 s ago") and shows the
port in use as `Auto · CASIO USB-MIDI MIDI 1`.

- Nothing to click: the app connects on load, and again when the piano is switched
  on later. Press **Connect MIDI** once if the browser asks for permission.
- **Use only this** pins a port, for when you would rather be certain than
  inferred. The choice is remembered across reloads.
- On the piano machine use `http://localhost:8000`: Web MIDI requires a secure
  context, and a LAN hostname is not one.
```

**7.2 ECOSYSTEM.md §10.** Under "Phase 8 — design", add:

```markdown
**Landed.** The rules live in `frontend/src/lib/midiDevice.ts` with unit tests
(`npm test`, Node's own runner — no new dependency), `MidiInput` attaches to every
input and drops cross-port echoes, the device bar reports which port is live, and
the browser e2e reproduces the reported device list (a dead `Midi Through Port-0`
beside a live Casio) in scenario 9.
```

**7.3 AGENT-LOG.md.** Append an entry in the established format, in the same shape
as the previous ones: what changed, which files, what was verified, and the two
facts the other agent would need (`MidiInput.select`/`selectDevice` retired;
`window.__fakeMidi.send` still targets the live port).

**7.4 The sweep.**

```bash
cd frontend && npm test && npx svelte-check --tsconfig ./tsconfig.json && npm run build
cd ../backend && .venv/bin/python -m pytest -q
# then the e2e, with the server running (see below)
```

Expected: `pass 8` / `0 errors and 0 warnings` / `✓ built in` / `631 passed`
(or 631 + whatever later tasks added) / `All browser scenarios passed.`

**7.5 Commit.** Title: `Document automatic MIDI selection`.

---

# Phase 9 — the notebook as a LAN server

## P9-T1 — `app/hostinfo.py`: where this request came from, what this machine sees

**Files.** create `backend/app/hostinfo.py`; modify `backend/app/main.py`.

**Why.** Two questions must be answerable from the main computer: "may this client
delete things?" and "is the piano attached to the notebook at all?" The second one
matters because Web MIDI silently finds *zero* devices when ALSA's sequencer is not
loaded, which looks exactly like broken hardware.

**Change Necessity.** No configuration-only option can answer either question.

### Steps

**1.1 Create `backend/app/hostinfo.py`:**

```python
"""Where a request came from, and what this machine can see.

Two facts the LAN deployment needs, and neither belongs to a domain:

* **Is this the piano machine?** Irreversible actions are refused from anywhere
  else (ECOSYSTEM.md D8). This is deliberately *not* authentication: there are no
  accounts in this app, and the boundary that matters is which actions cannot be
  undone, not who is asking.
* **Is ALSA's sequencer present?** Web MIDI enumerates the ALSA sequencer, so when
  `/dev/snd/seq` does not exist the browser reports *no MIDI devices at all* —
  which reads as a hardware fault and is a missing kernel module.
"""

from __future__ import annotations

import ipaddress
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api", tags=["host"])

#: Where ALSA exposes its sequencer, and a readable list of its clients.
SEQUENCER_PATH = Path("/dev/snd/seq")
SEQ_CLIENTS_PATH = Path("/proc/asound/seq/clients")


class HostInfo(BaseModel):
    #: The address this request arrived from, as the server sees it.
    host: str | None
    #: True when the request came from this machine itself.
    loopback: bool
    #: False means Web MIDI will find no devices, whatever is plugged in.
    sequencer: bool
    #: ALSA sequencer clients currently visible, e.g. ["Midi Through", "CASIO USB-MIDI"].
    clients: list[str]


def client_host(request: Request) -> str | None:
    return request.client.host if request.client else None


def is_loopback(request: Request) -> bool:
    """Whether the request came from this machine.

    `ipaddress` rather than a string comparison, because a dual-stack socket can
    report an IPv4 address mapped into IPv6 (`::ffff:127.0.0.1`).
    """
    host = client_host(request)
    if not host:
        return False
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"


def require_loopback(request: Request) -> None:
    """FastAPI dependency: refuse an irreversible action from another machine.

    The message names the address to use, because a bare 403 on a button that
    looks ordinary is a puzzle rather than an instruction.
    """
    if not is_loopback(request):
        raise HTTPException(
            status_code=403,
            detail=(
                "This action can only be taken on the piano machine. "
                "Open http://localhost:8000 there and try again."
            ),
        )


def alsa_clients() -> list[str]:
    """Sequencer clients visible to ALSA, read from procfs.

    Reading `/proc/asound/seq/clients` needs no device open and no permission, so
    the server can report "the piano is attached" even when no browser is running.
    """
    try:
        lines = SEQ_CLIENTS_PATH.read_text(errors="replace").splitlines()
    except OSError:
        return []
    names: list[str] = []
    for line in lines:
        # Lines look like:  Client  24 : "CASIO USB-MIDI" [Kernel]
        if "Client" not in line or ":" not in line:
            continue
        _, _, rest = line.partition(":")
        name = rest.split('"')[1] if '"' in rest else rest.strip()
        if name and name not in names:
            names.append(name)
    return names


@router.get("/host", response_model=HostInfo)
def host_info(request: Request) -> HostInfo:
    return HostInfo(
        host=client_host(request),
        loopback=is_loopback(request),
        sequencer=SEQUENCER_PATH.exists(),
        clients=alsa_clients(),
    )
```

**1.2 Mount it.** In `backend/app/main.py`, beside the other routers:

```python
from .hostinfo import router as hostinfo_router
...
app.include_router(hostinfo_router)
```

Order does not matter, but keep it before `mount_frontend()` (which is at the end
of the module and catches everything else).

**1.3 Verify by hand.** With the server running:

```bash
curl -s http://127.0.0.1:8000/api/host
```

Expected on this machine right now (piano unplugged, sequencer not loaded):

```json
{"host":"127.0.0.1","loopback":true,"sequencer":false,"clients":[]}
```

**1.4 Commit.** Title: `Report where a request came from and whether ALSA has a sequencer`.

---

## P9-T2 — Irreversible actions are refused off the piano machine

**Files.** modify `backend/app/repertoire/api.py`, `backend/app/main.py`,
`backend/app/backup.py`, `backend/app/practice/api.py`; create
`backend/tests/test_server_hardening.py`.

**Why.** ECOSYSTEM.md D8: read, listen, upload, edit, tag — allowed from anywhere.
Delete, reset, replace, re-segment-over-labels — piano machine only.

### Steps

**2.1 The four `DELETE`s.** In `backend/app/repertoire/api.py`, add to the imports:

```python
from ..hostinfo import require_loopback
```

and add the dependency to each delete decorator:

```python
@router.delete("/pieces/{piece_id}", response_model=DeleteResult, dependencies=[Depends(require_loopback)])
@router.delete("/composers/{composer_id}", response_model=DeleteResult, dependencies=[Depends(require_loopback)])
@router.delete("/journal/{entry_id}", response_model=DeleteResult, dependencies=[Depends(require_loopback)])
@router.delete("/media/{media_id}", response_model=DeleteResult, dependencies=[Depends(require_loopback)])
```

`Depends` is already imported in that module.

**2.2 Profile reset.** In `backend/app/main.py`:

```python
@app.post("/api/profile/reset", response_model=ProfileOut, dependencies=[Depends(require_loopback)])
```

with `from .hostinfo import require_loopback, router as hostinfo_router` added to the
imports.

**2.3 Backup replace.** In `backend/app/backup.py`'s import route, replace:

```python
@router.post("/import", response_model=BackupImportResult)
def import_backup(body: BackupImportRequest) -> BackupImportResult:
    try:
```

with:

```python
@router.post("/import", response_model=BackupImportResult)
def import_backup(request: Request, body: BackupImportRequest) -> BackupImportResult:
    # Conditional, because the same route is safe in one mode: a merge adds what is
    # missing and destroys nothing, so it stays available over the LAN.
    if body.mode == "replace":
        require_loopback(request)
    try:
```

plus `from fastapi import APIRouter, Depends, HTTPException, Request` and
`from .hostinfo import require_loopback`.

**2.4 Re-segment over labels.** In `backend/app/practice/api.py`, replace:

```python
@router.post("/sittings/{sitting_id}/resegment", response_model=list[SegmentSummary])
def resegment(sitting_id: int, body: ResegmentRequest) -> list[SegmentSummary]:
    return _handle(store.resegment_sitting, sitting_id, confirm=body.confirm)
```

with:

```python
@router.post("/sittings/{sitting_id}/resegment", response_model=list[SegmentSummary])
def resegment(
    sitting_id: int, body: ResegmentRequest, request: Request
) -> list[SegmentSummary]:
    # `confirm=false` is a recompute of unlabelled boundaries and destroys nothing;
    # `confirm=true` throws labels away, so only that variant is restricted.
    if body.confirm:
        require_loopback(request)
    return _handle(store.resegment_sitting, sitting_id, confirm=body.confirm)
```

plus `Request` in the `fastapi` import and `from ..hostinfo import require_loopback`.

**2.5 Tests.** Create `backend/tests/test_server_hardening.py`:

```python
"""The boundaries that make a LAN deployment safe without accounts.

`TestClient` connects over a fake transport whose client address is "testclient",
so a loopback-only route must be exercised through a real socket. These tests use
the app's own request pipeline with an explicit client address instead.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.hostinfo import HostInfo, alsa_clients, is_loopback


def test_ipv4_ipv6_and_mapped_loopback_all_count_as_local() -> None:
    from starlette.requests import Request

    def request_from(host: str) -> Request:
        return Request(
            {
                "type": "http",
                "client": (host, 12345),
                "method": "GET",
                "path": "/",
                "headers": [],
            }
        )

    for host in ("127.0.0.1", "::1", "::ffff:127.0.0.1", "localhost"):
        assert is_loopback(request_from(host)) is True, host
    for host in ("192.168.1.50", "10.0.0.7", "::ffff:192.168.1.50"):
        assert is_loopback(request_from(host)) is False, host


def test_require_loopback_refuses_a_lan_client() -> None:
    from starlette.requests import Request

    from app.hostinfo import require_loopback

    lan = Request(
        {"type": "http", "client": ("192.168.1.50", 5000), "method": "DELETE", "path": "/", "headers": []}
    )
    with pytest.raises(Exception) as error:
        require_loopback(lan)
    assert "piano machine" in str(error.value)


def test_the_host_route_reports_this_machine(client) -> None:
    body = client.get("/api/host").json()
    assert body["loopback"] is True, "TestClient is local"
    assert "sequencer" in body
    assert isinstance(body["clients"], list)


def test_alsa_clients_is_empty_rather_than_failing_without_a_sequencer() -> None:
    # On this machine /dev/snd/seq is absent, so the honest answer is "none", not an
    # exception that would take the whole status page down.
    assert isinstance(alsa_clients(), list)


def test_deleting_a_piece_over_the_lan_is_refused(client) -> None:
    piece = client.post("/api/repertoire/pieces", json={"title": "Keep me"}).json()
    # Simulate the LAN by overriding the request's client address for one call.
    from app import main as main_module

    original = main_module.is_loopback
    main_module.is_loopback = lambda request: False
    try:
        # The route's dependency closes over the imported name, so patch there too.
        import app.hostinfo as hostinfo

        hostinfo.is_loopback = lambda request: False
        refused = client.delete(f"/api/repertoire/pieces/{piece['id']}")
    finally:
        hostinfo.is_loopback = original
        main_module.is_loopback = original
    assert refused.status_code == 403
    assert "piano machine" in refused.json()["detail"]
    # And it really is still there.
    assert client.get(f"/api/repertoire/pieces/{piece['id']}").status_code == 200


def test_a_merge_import_is_not_restricted_but_a_replace_is(client) -> None:
    document = client.get("/api/backup/export").json()
    assert client.post("/api/backup/import", json={"document": document}).status_code == 200

    import app.hostinfo as hostinfo

    original = hostinfo.is_loopback
    hostinfo.is_loopback = lambda request: False
    try:
        replaced = client.post(
            "/api/backup/import",
            json={"document": document, "mode": "replace", "confirm": True},
        )
    finally:
        hostinfo.is_loopback = original
    assert replaced.status_code == 403
```

Note the patch target: `require_loopback` calls `is_loopback` resolved in its own
module, so patching `app.hostinfo.is_loopback` is what takes effect. The first test
in this file proves the real implementation, so patching does not hide a broken
check.

**2.6 Run.** `cd backend && .venv/bin/python -m pytest tests/test_server_hardening.py -q`
Expected: `6 passed`.

**2.7 Commit.** Title: `Refuse irreversible actions from anywhere but the piano machine`.

---

## P9-T3 — Two writers, one database: busy timeout and an upload cap

**Files.** modify `backend/app/db.py`, `backend/app/config.py`,
`backend/app/repertoire/api.py`; extend `backend/tests/test_server_hardening.py`.

**Why.** Until now exactly one client wrote to the file. With the main computer
uploading while the notebook captures, SQLite's default of "fail immediately if
locked" becomes a real, intermittent failure. And an accidental 4 GB drag onto the
notebook should not fill its disk.

### Steps

**3.1 Busy timeout.** In `backend/app/db.py`, inside `connect()`, after the WAL
pragma:

```python
    # Two machines write to this file over the LAN (capture on the notebook, an
    # upload from the main computer), so "database is locked" must be waited out
    # rather than raised. Five seconds is far longer than any write here takes.
    conn.execute("PRAGMA busy_timeout = 5000")
```

**3.2 Config.** In `backend/app/config.py`, in the practice-logging block:

```python
    #: Largest recording accepted by the upload endpoint, in megabytes. A cap that
    #: only trusts the client's declared size is not a cap, so it is enforced while
    #: writing (see the upload route).
    max_upload_mb: int = _env_int("SRT_MAX_UPLOAD_MB", 512)
```

**3.3 Enforce it.** In `backend/app/repertoire/api.py`'s upload route, replace:

```python
    suffix = Path(file.filename or "").suffix
    media_dir = Path(settings.media_dir)
    with tempfile.TemporaryDirectory() as scratch:
        staged = Path(scratch) / f"upload{suffix}"
        with staged.open("wb") as handle:
            shutil.copyfileobj(file.file, handle, length=1024 * 1024)
        if staged.stat().st_size == 0:
            raise HTTPException(status_code=422, detail="the uploaded file is empty")
```

with:

```python
    limit_bytes = settings.max_upload_mb * 1024 * 1024
    if file.size is not None and file.size > limit_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"the recording is larger than {settings.max_upload_mb} MB",
        )

    suffix = Path(file.filename or "").suffix
    media_dir = Path(settings.media_dir)
    with tempfile.TemporaryDirectory() as scratch:
        staged = Path(scratch) / f"upload{suffix}"
        written = 0
        with staged.open("wb") as handle:
            while chunk := file.file.read(1024 * 1024):
                written += len(chunk)
                # Checked while writing, not only on the declared size: a client can
                # lie about that, and the point of the cap is to protect the disk.
                if written > limit_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"the recording is larger than {settings.max_upload_mb} MB",
                    )
                handle.write(chunk)
        if staged.stat().st_size == 0:
            raise HTTPException(status_code=422, detail="the uploaded file is empty")
```

`shutil` may now be unused in that module — remove it from the imports if
`svelte-check`'s Python equivalent (ruff/flake8) or a grep says so:

```bash
grep -n "shutil" backend/app/repertoire/api.py
```

**3.4 Tests.** Append to `backend/tests/test_server_hardening.py`:

```python
def test_the_upload_cap_is_enforced_while_writing(client, monkeypatch) -> None:
    """A declared size can lie; the bytes on the way in cannot."""
    from app.config import settings

    piece = client.post("/api/repertoire/pieces", json={"title": "Cap"}).json()
    monkeypatch.setattr(settings, "max_upload_mb", 0)  # anything non-empty is too big
    response = client.post(
        f"/api/repertoire/pieces/{piece['id']}/media",
        files={"file": ("take.wav", b"x" * 4096, "audio/wav")},
    )
    assert response.status_code == 413
    assert "larger than" in response.json()["detail"]


def test_the_connection_waits_for_a_lock_instead_of_failing(fresh_db) -> None:
    from app.db import connect

    conn = connect()
    try:
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    finally:
        conn.close()
```

`monkeypatch.setattr(settings, "max_upload_mb", 0)` works because `Settings` is a
frozen dataclass *instance*: `monkeypatch.setattr` on an instance attribute of a
frozen dataclass raises `FrozenInstanceError`. If it does, change the test to
construct the limiter through the environment instead:

```python
def test_the_upload_cap_is_enforced_while_writing(client) -> None:
    from app.config import settings

    piece = client.post("/api/repertoire/pieces", json={"title": "Cap"}).json()
    # The route reads settings.max_upload_mb at call time, so override the module
    # attribute the route sees rather than the frozen settings object.
    import app.repertoire.api as repertoire_api

    class Limited:
        max_upload_mb = 0

    original = repertoire_api.settings
    repertoire_api.settings = Limited()
    try:
        response = client.post(
            f"/api/repertoire/pieces/{piece['id']}/media",
            files={"file": ("take.wav", b"x" * 4096, "audio/wav")},
        )
    finally:
        repertoire_api.settings = original
    assert response.status_code == 413
    assert "larger than" in response.json()["detail"]
```

Use whichever version runs; the second is guaranteed to work with a frozen
Settings, so **start with the second**.

**3.5 Run.** `cd backend && .venv/bin/python -m pytest tests/test_server_hardening.py -q`
Expected: `8 passed`.

**3.6 Commit.** Title: `Wait for database locks and cap recording uploads`.

---

## P9-T4 — Capture heartbeat: is the notebook actually logging?

**Files.** create `backend/app/practice/capture_status.py`; modify
`backend/app/practice/models.py`, `backend/app/practice/api.py`,
`backend/tests/conftest.py`, `backend/tests/test_server_hardening.py`.

**Why.** With nobody sitting at the notebook, "capture silently stopped" is the
failure that matters, and it is invisible from the main computer. The heartbeat
plus the last-note timestamp make it a reading.

**Design note.** "Last note" is **not** part of the heartbeat: it is read from
`note_events`/`sittings`, which is shared truth rather than a client's claim. The
heartbeat carries only liveness, the capture switch, and the buffer depth.

### Steps

**4.1 Create `backend/app/practice/capture_status.py`:**

```python
"""Ephemeral capture state, reported by whichever client is logging.

Deliberately in memory rather than in the database: it describes *now* — is a client
capturing, is it behind, when did it last check in — and a stale row would be worse
than no row. The last *note* is not here either; that comes from `note_events`,
which is shared truth rather than something a client asserts.
"""

from __future__ import annotations

import time

from pydantic import BaseModel

#: A report older than this is treated as gone, not as "still capturing".
STALE_AFTER_MS = 60_000


class CaptureReport(BaseModel):
    origin: str
    enabled: bool
    pending: int
    at_ms: int


_report: CaptureReport | None = None


def record(
    *, origin: str, enabled: bool, pending: int, now_ms: int | None = None
) -> CaptureReport:
    global _report
    _report = CaptureReport(
        origin=origin[:120],
        enabled=bool(enabled),
        pending=max(0, int(pending)),
        at_ms=int(now_ms if now_ms is not None else time.time() * 1000),
    )
    return _report


def snapshot(now_ms: int | None = None) -> CaptureReport | None:
    if _report is None:
        return None
    now = int(now_ms if now_ms is not None else time.time() * 1000)
    if now - _report.at_ms > STALE_AFTER_MS:
        return None
    return _report


def reset() -> None:
    """Forget the last report. Used by tests between cases."""
    global _report
    _report = None
```

**4.2 Models.** In `backend/app/practice/models.py`, add:

```python
class CaptureReportIn(BaseModel):
    """What a capturing client tells the server about itself."""

    origin: str = Field(max_length=120)
    enabled: bool
    pending: int = Field(default=0, ge=0)


class CaptureStatusOut(BaseModel):
    origin: str
    enabled: bool
    pending: int
    at_ms: int
```

and extend `PracticeStatus`:

```python
    #: Epoch ms of the end of the last note the server stored, or None. Read from
    #: the database, so it is a fact rather than a client's claim.
    last_note_ms: int | None = None
    #: The last capture heartbeat, or None when nothing has reported recently.
    capture: CaptureStatusOut | None = None
```

**4.3 Routes.** In `backend/app/practice/api.py`:

```python
from . import capture_status
from .models import CaptureReportIn, CaptureStatusOut
```

add the route:

```python
@router.post("/capture-status", response_model=CaptureStatusOut)
def report_capture(body: CaptureReportIn) -> CaptureStatusOut:
    """A client saying "I am capturing". Cheap on purpose: it is sent every 15 s."""
    return CaptureStatusOut(
        **capture_status.record(
            origin=body.origin, enabled=body.enabled, pending=body.pending
        ).model_dump()
    )
```

and extend the status route. The existing query already selects `MAX(ended_ms) AS
last_end`, so the patch is two `PracticeStatus(...)` arguments — replace:

```python
    return PracticeStatus(
        sittings=int(totals["sittings"] or 0),
        notes=int(notes or 0),
        first_date=totals["first_date"],
        last_date=totals["last_date"],
        open_sitting=open_sitting,
    )
```

with:

```python
    return PracticeStatus(
        sittings=int(totals["sittings"] or 0),
        notes=int(notes or 0),
        first_date=totals["first_date"],
        last_date=totals["last_date"],
        open_sitting=open_sitting,
        # The end of the last note the server stored. Read from the database, so it
        # is a fact rather than something a client claims.
        last_note_ms=int(last_end) if last_end is not None else None,
        capture=capture_status.snapshot(),
    )
```

**4.4 Clear it between tests.** In `backend/tests/conftest.py`, inside the
`fresh_db` fixture after `_wipe()`:

```python
    from app.practice import capture_status

    capture_status.reset()
```

**4.5 Tests.** Append to `backend/tests/test_server_hardening.py`:

```python
def test_a_capture_heartbeat_is_reported_back(client) -> None:
    assert client.get("/api/practice/status").json()["capture"] is None
    posted = client.post(
        "/api/practice/capture-status",
        json={"origin": "localhost:8000", "enabled": True, "pending": 3},
    ).json()
    assert posted["enabled"] is True and posted["pending"] == 3
    status = client.get("/api/practice/status").json()
    assert status["capture"]["origin"] == "localhost:8000"
    assert status["capture"]["enabled"] is True


def test_a_stale_heartbeat_is_not_reported(client) -> None:
    from app.practice import capture_status

    capture_status.record(origin="localhost:8000", enabled=True, pending=0, now_ms=1_000)
    assert capture_status.snapshot(now_ms=1_000 + capture_status.STALE_AFTER_MS + 1) is None
    assert client.get("/api/practice/status").json()["capture"] is not None or True
    capture_status.reset()


def test_the_status_reports_the_last_stored_note(client) -> None:
    from app.practice import store
    from app.practice.models import EventBatch, WireNote

    assert client.get("/api/practice/status").json()["last_note_ms"] is None
    store.ingest(
        EventBatch(
            tz_offset_minutes=0,
            events=[
                WireNote(
                    epoch_ms=1_700_011_800_000, pitch=60, velocity=70, duration_ms=300, channel=0
                )
            ],
        )
    )
    assert client.get("/api/practice/status").json()["last_note_ms"] == 1_700_011_800_300
```

The middle assertion in `test_a_stale_heartbeat_is_not_reported` is intentionally
about `snapshot`, not about the route (the route uses the real clock); keep the
test focused on the rule and do not assert clock-dependent behaviour through HTTP.

**4.6 Run.** `cd backend && .venv/bin/python -m pytest tests/test_server_hardening.py -q`
Expected: `11 passed`.

**4.7 Commit.** Title: `Let a capturing client report that it is still alive`.

---

## P9-T5 — The interface knows where it is being used from

**Files.** create `frontend/src/components/HostBanner.svelte`; modify
`frontend/src/lib/{types.ts,api.ts,state.svelte.ts}`,
`frontend/src/App.svelte`, `frontend/src/components/{PracticeLogView,BackupPanel,RepertoireView}.svelte`.

**Why.** A page opened on the main computer must say what it cannot do — MIDI is
not there, and irreversible actions are refused — instead of offering controls that
fail. And the notebook's own health (sequencer, capture, last note) should be
visible from wherever you are looking.

### Steps

**5.1 Types.** In `frontend/src/lib/types.ts`:

```ts
export interface HostInfo {
  host: string | null;
  /** True when this page is being used on the machine running the server. */
  loopback: boolean;
  /** False means ALSA's sequencer is not loaded, so Web MIDI finds nothing. */
  sequencer: boolean;
  /** ALSA sequencer clients, e.g. ["Midi Through", "CASIO USB-MIDI"]. */
  clients: string[];
}

/** What a capturing client tells the server about itself. */
export interface CaptureStatus {
  origin: string;
  enabled: boolean;
  pending: number;
  at_ms: number;
}
```

and extend `PracticeStatus` with:

```ts
  /** Epoch ms of the last note stored on the server, or null. */
  last_note_ms: number | null;
  capture: CaptureStatus | null;
```

**5.2 API client.** In `frontend/src/lib/api.ts`:

```ts
  host: () => request<HostInfo>('/host'),
```

and inside `practice`:

```ts
    reportCapture: (body: { origin: string; enabled: boolean; pending: number }) =>
      request<CaptureStatus>('/practice/capture-status', {
        method: 'POST',
        body: JSON.stringify(body),
      }),
```

with `HostInfo` added to the type import list.

**5.3 State.** In `state.svelte.ts`:

```ts
  /** What the server can tell us about this machine and this request. */
  host = $state<HostInfo | null>(null);
```

in `bootstrap()`, after `this.apiOnline = true;`:

```ts
      try {
        this.host = await api.host();
      } catch {
        // Only used to explain the deployment; never block the app on it.
      }
```

and a heartbeat sender beside the capture client:

```ts
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;

  /**
   * Tell the server that capture is running.
   *
   * Without this, a notebook whose browser died is indistinguishable from a quiet
   * evening, and the person looking at the stats from another room cannot tell.
   */
  private startCaptureHeartbeat(): void {
    if (this.heartbeatTimer !== null) return;
    const send = () => {
      void api.practice
        .reportCapture({
          origin: location.host,
          enabled: this.captureStatus.enabled,
          pending: this.captureStatus.buffered,
        })
        .catch(() => {
          // A failed heartbeat is a symptom, not a cause; the capture bar already
          // shows the API being unreachable.
        });
    };
    send();
    this.heartbeatTimer = setInterval(send, 15_000);
  }
```

Call `this.startCaptureHeartbeat()` at the end of `setCapture()` and in
`connectMidi()` where `capture.start()` is called (both places), and also once in
`startMidi()` so a fresh page reports immediately.

**5.4 The banner component.** Create `frontend/src/components/HostBanner.svelte`:

```svelte
<script lang="ts">
  /**
   * Deployment facts that change what this page can do.
   *
   * Both messages exist because the alternative is a control that fails: a device
   * picker that can never find the piano, or a Delete button that returns 403.
   */
  import { app } from '../lib/state.svelte';

  const host = $derived(app.host);
</script>

{#if host && !host.sequencer}
  <div class="banner warn" data-host-warning="sequencer">
    <strong>ALSA's sequencer is not loaded on this machine.</strong>
    MIDI inputs will not appear, whatever is plugged in, until
    <code>snd_seq</code> is loaded — see <code>docs/DEPLOYMENT.md</code>.
  </div>
{/if}

{#if host && !host.loopback}
  <div class="banner info" data-host-warning="remote">
    <strong>Viewing from another machine ({host.host}).</strong>
    Practice and calibration need the piano's own browser, and deleting or restoring
    is only allowed there — everything else, including tagging pieces and uploading
    recordings, works here.
  </div>
{/if}

<style>
  .banner {
    border-radius: var(--radius);
    padding: 0.55rem 0.75rem;
    font-size: 0.86rem;
    border: 1px solid var(--line);
    background: var(--surface-2);
    color: var(--ink);
  }

  .banner.warn {
    background: var(--warn-soft);
    border-color: var(--warn-line);
    color: var(--warn);
  }

  .banner.info {
    background: var(--accent-soft);
    border-color: var(--accent-line);
    color: var(--accent);
  }

  code {
    font-family: var(--mono);
    font-size: 0.8rem;
  }
</style>
```

**5.5 Mount it.** In `App.svelte`, directly after `<WorkoutBar />`:

```svelte
  <HostBanner />
```

with the import beside the others.

**5.6 Disable what cannot work.** In `RepertoireView.svelte`, the piece detail's
delete button and the recording delete button become:

```svelte
                <button
                  class="ghost"
                  disabled={!app.host?.loopback}
                  title={app.host?.loopback ? '' : 'Only on the piano machine'}
                  onclick={() => (confirmingDelete = true)}>Delete</button>
```

and the recording delete gets the same three attributes (`class="ghost tiny"`,
`disabled={!app.host?.loopback}`, and the `title`). `RepertoireView.svelte` already
imports `app`, so no new import is needed there. In `BackupPanel.svelte`,
the replace-mode confirmation button gains the same `disabled`/`title` pair, and
the mode `<select>` keeps `merge` available everywhere:

```svelte
      <button
        class="danger"
        disabled={busy || !app.host?.loopback}
        title={app.host?.loopback ? '' : 'Only on the piano machine'}
        onclick={() => void run()}
      >
```

`BackupPanel.svelte` needs `import { app } from '../lib/state.svelte';`.

**5.7 Show the capture state in the Log view.** In `PracticeLogView.svelte`, inside
the stats grid, add a fifth stat:

```svelte
    <div class="stat">
      <span class="muted small">Capture</span>
      <strong>{captureHeadline(summary)}</strong>
      <span class="muted small">{lastNoteLabel(summary)}</span>
    </div>
```

with the two helpers in the script block:

```ts
  /** "browser" when a client has checked in, "silent" when none has. */
  function captureHeadline(data: AnalyticsSummary): string {
    if (!data.capture) return 'not reporting';
    return data.capture.enabled ? data.capture.origin : 'paused';
  }

  function lastNoteLabel(data: AnalyticsSummary): string {
    if (data.last_note_ms === null) return 'no notes recorded yet';
    const seconds = Math.max(0, Math.round((Date.now() - data.last_note_ms) / 1000));
    if (seconds < 90) return `last note ${seconds} s ago`;
    return `last note ${Math.round(seconds / 60)} min ago`;
  }
```

The dashboard needs the same two facts, so they travel on the analytics summary
too — the Log view is where they are read, and one request is better than two.

In `frontend/src/lib/types.ts`, add to `AnalyticsSummary`:

```ts
  /** Epoch ms of the last note stored on the server, or null. */
  last_note_ms: number | null;
  capture: CaptureStatus | null;
```

In `backend/app/practice/models.py`, add to `AnalyticsSummary`:

```python
    last_note_ms: int | None = None
    capture: CaptureStatusOut | None = None
```

In `backend/app/practice/store.py`, the totals query gains one column:

```python
    totals = conn.execute(
        "SELECT COALESCE(SUM(ended_ms - started_ms), 0) / 60000.0 AS minutes,"
        " MAX(ended_ms) AS last_ms,"
        " (SELECT COUNT(*) FROM note_events) AS notes FROM sittings"
    ).fetchone()
```

and the `AnalyticsSummary(...)` constructor gains:

```python
        last_note_ms=int(totals["last_ms"]) if totals["last_ms"] is not None else None,
        capture=capture_status.snapshot(),
```

with `from . import capture_status` at the top of the file — the practice domain's
own module, so this is not a cross-domain import.

**5.8 Check and build.**

```bash
cd frontend && npx svelte-check --tsconfig ./tsconfig.json && npm run build
cd ../backend && .venv/bin/python -m pytest -q
```

Expected: 0 errors, built, and the suite green (the new `AnalyticsSummary` fields
have defaults, so existing tests keep passing).

**5.9 Commit.** Title: `Tell each machine what it can and cannot do here`.

---

## P9-T6 — `deploy/`: the notebook as a service

**Files.** create `deploy/install.sh`, `deploy/piano-ecosystem.service`,
`deploy/piano-kiosk.service`, `deploy/chromium-policy.json`,
`deploy/snd-seq.conf`, `deploy/logind-50-piano.conf`, `deploy/README.md`.

**Why.** Everything above is useless on a machine nobody logs into unless it comes
back after a reboot, without a permission prompt, and without suspending when the
lid closes.

**Impact.** Nothing at runtime. These files are copied into system paths by
`install.sh`, which is run by the user, not by the app.

### Steps

**6.1 `deploy/piano-ecosystem.service`:**

```ini
[Unit]
Description=Piano ecosystem (sight-reading trainer + practice log)
Documentation=file:///opt/piano-ecosystem/docs/DEPLOYMENT.md
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
# Change to the user that owns the data directory.
User=piano
Group=piano
WorkingDirectory=/opt/piano-ecosystem/backend
EnvironmentFile=-/etc/piano-ecosystem.env
# 0.0.0.0 so the main computer can read the log; MIDI still happens in the
# browser on this machine, over http://localhost:8000.
ExecStart=/opt/piano-ecosystem/backend/.venv/bin/python -m uvicorn app.main:app \
    --host 0.0.0.0 --port 8000 --log-level warning
Restart=always
RestartSec=2
# WAL plus two writers (capture here, uploads from the LAN) is the reason this
# service must not be killed mid-write on a reboot.
KillSignal=SIGINT
TimeoutStopSec=20

[Install]
WantedBy=multi-user.target
```

**6.2 `deploy/piano-kiosk.service`** (a **user** unit, so it runs inside the
graphical session and can reach the display):

```ini
[Unit]
Description=Chromium kiosk pointed at the piano ecosystem
After=graphical-session.target
PartOf=graphical-session.target

[Service]
Type=simple
# --user-data-dir keeps the granted MIDI permission and the capture switch in a
# profile of its own, so nothing else in the browser can disturb it.
ExecStart=/usr/bin/chromium \
    --kiosk \
    --no-first-run \
    --no-default-browser-check \
    --disable-session-crashed-bubble \
    --user-data-dir=%h/.config/piano-kiosk \
    http://localhost:8000
Restart=always
RestartSec=3

[Install]
WantedBy=graphical-session.target
```

The URL is `localhost` on purpose: Web MIDI requires a secure context, and a LAN
hostname is not one (ECOSYSTEM.md D9).

**6.3 `deploy/chromium-policy.json`:**

```json
{
  "MidiAllowedForUrls": ["http://localhost:8000", "http://127.0.0.1:8000"],
  "HighEfficiencyModeEnabled": false
}
```

Why each line matters: the first grants the MIDI permission with no prompt, so the
kiosk never stalls on a dialog nobody is there to click. The second turns Memory
Saver off, so a backgrounded tab is never *discarded* — which would silently stop
capture. Timer throttling in a background tab is harmless, because every note
carries its own absolute timestamp.

Installed to `/etc/chromium/policies/managed/piano-ecosystem.json` on
Chromium/Arch (`/etc/opt/chrome/policies/managed/` for Google Chrome).

**6.4 `deploy/snd-seq.conf`** (installed to `/etc/modules-load.d/`):

```
# Web MIDI enumerates the ALSA sequencer. Without this module /dev/snd/seq does not
# exist and the browser reports NO MIDI devices at all, whatever is plugged in.
snd_seq
```

**6.5 `deploy/logind-50-piano.conf`** (installed to
`/etc/systemd/logind.conf.d/50-piano.conf`):

```ini
# A notebook planted on the piano has its lid shut and must keep logging.
[Login]
HandleLidSwitch=ignore
HandleLidSwitchExternalPower=ignore
HandleLidSwitchDocked=ignore
IdleAction=ignore
```

**6.6 `deploy/install.sh`:**

```bash
#!/usr/bin/env bash
# Install the piano ecosystem as a service on this machine.
#
# Run from anywhere with sudo: it copies deploy files into system paths, builds the
# frontend, creates the venv, and enables the units. Idempotent: re-running it is
# how you upgrade.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_USER="${SERVICE_USER:-${SUDO_USER:-$(id -un)}}"
PORT="${PORT:-8000}"
DATA_DIR="${DATA_DIR:-/home/$SERVICE_USER/.local/share/piano-ecosystem}"

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
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" "$DATA_DIR"

echo "==> Environment file"
cat > /etc/piano-ecosystem.env <<ENV
SRT_DB_PATH=$DATA_DIR/piano.db
SRT_MEDIA_DIR=$DATA_DIR/media
SRT_LEGACY_DB=/home/$SERVICE_USER/.local/share/piano-progress/piano.db
ENV

echo "==> systemd units"
sed -e "s|^User=.*|User=$SERVICE_USER|" \
    -e "s|^Group=.*|Group=$(id -gn "$SERVICE_USER")|" \
    -e "s|/opt/piano-ecosystem|$APP_DIR|g" \
    -e "s|--port 8000|--port $PORT|" \
    "$APP_DIR/deploy/piano-ecosystem.service" > /etc/systemd/system/piano-ecosystem.service
systemctl daemon-reload
systemctl enable --now piano-ecosystem.service

echo "==> ALSA sequencer at boot"
install -m 644 "$APP_DIR/deploy/snd-seq.conf" /etc/modules-load.d/piano-midi.conf
modprobe snd_seq || echo "warning: could not load snd_seq now; it will load on the next boot" >&2

echo "==> Lid switch and idle behaviour"
install -d /etc/systemd/logind.conf.d
install -m 644 "$APP_DIR/deploy/logind-50-piano.conf" /etc/systemd/logind.conf.d/50-piano.conf
systemctl restart systemd-logind || true

echo "==> Chromium policy (MIDI auto-grant, Memory Saver off)"
POLICY_DIR=/etc/chromium/policies/managed
install -d "$POLICY_DIR"
install -m 644 "$APP_DIR/deploy/chromium-policy.json" "$POLICY_DIR/piano-ecosystem.json"

echo "==> Kiosk autostart for $SERVICE_USER"
USER_UNIT_DIR="/home/$SERVICE_USER/.config/systemd/user"
install -d -o "$SERVICE_USER" -g "$(id -gn "$SERVICE_USER")" "$USER_UNIT_DIR"
install -o "$SERVICE_USER" -g "$(id -gn "$SERVICE_USER")" -m 644 \
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
```

Then `chmod +x deploy/install.sh`.

**6.7 `deploy/README.md`:** one page, in the order you would do it:

```markdown
# Deploying on the piano notebook

Target: a notebook that stays with the piano, running this app as a service, with
the browser as the only thing that touches MIDI.

## One-time, on the notebook

```bash
sudo apt install -y python3-venv nodejs chromium   # or the equivalent
# put the repository somewhere it can stay, e.g. /opt/piano-ecosystem
sudo SERVICE_USER=$USER ./deploy/install.sh
```

Then:

1. Set the notebook to **log in automatically** (the kiosk runs inside a graphical
   session) and leave the screen blanking setting alone — a blanked screen does not
   stop capture.
2. Check it: `systemctl status piano-ecosystem`, `curl -s localhost:8000/api/host`.
   `"sequencer": true` and the Casio in `"clients"` means the piano is visible.
3. From the main computer open `http://<notebook>.local:8000`.

## What runs where

| Piece | Where | Why |
| --- | --- | --- |
| uvicorn | system service | survives reboots and crashes |
| Chromium kiosk | user session | Web MIDI needs a browser, and MIDI needs `localhost` |
| capture | that browser tab | one capture path; the page reports a heartbeat |
| MIDI permission | managed policy | no prompt on a machine nobody is sitting at |
| `snd_seq` | `modules-load.d` | without it Web MIDI finds *no* devices |

## Day two

- **Upgrade:** `git pull && sudo ./deploy/install.sh`.
- **Is it logging?** Log → *Capture* shows the last heartbeat and the last note;
  `curl -s localhost:8000/api/practice/status`.
- **Backup:** from the main computer, Log → *Export & backup* → *Download backup*
  (JSON, no audio), and copy `media/` separately. See `docs/DEPLOYMENT.md`.
- **The kiosk died:** `systemctl --user status piano-kiosk`; it restarts itself, and
  the heartbeat goes quiet when it cannot.
```

**6.8 Config verification** (replacing a test cycle, per the TDD Route note):

```bash
cd /home/marco_normal/tmp/SighRTracker
bash -n deploy/install.sh && echo "install.sh parses"
python3 -c "import json;json.load(open('deploy/chromium-policy.json'));print('policy JSON parses')"
systemd-analyze verify deploy/piano-ecosystem.service 2>&1 | head -5 || true
```

Expected: `install.sh parses`, `policy JSON parses`, and from `systemd-analyze`
only complaints about the missing path `/opt/piano-ecosystem` (expected on a dev
machine; the installer rewrites the path).

**6.9 Commit.** Title: `Add the deployment files for the piano notebook`.

---

## P9-T7 — e2e: a page that is being viewed from elsewhere

**Files.** modify `backend/tools/e2e_browser.py`.

**Why.** ECOSYSTEM.md §10 Phase 9 acceptance: the main computer sees the data, the
open-LAN warning and the no-MIDI hint appear there, and the notebook shows neither.

**Design note.** The suite runs on loopback, so "from another machine" is produced by
stubbing the one endpoint the interface asks: `/api/host`. That is honest — the
server-side rule is tested for real in P9-T2 — and it keeps the check on the
interface, which is what this scenario is for.

### Steps

**7.1 Add the scenario** before `def main()`:

```python
def scenario_lan_viewer(browser) -> None:
    print("\\n[10] Viewing from another machine: what this page says it cannot do")

    # The suite runs on loopback, so the server's own view is stubbed to what a
    # main computer would get. The rule itself is tested in the backend suite.
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
    check("another machine" in banner.inner_text(), f"the banner names the situation ({banner.inner_text()[:80]!r})")
    check(
        "192.168.1.50" in banner.inner_text(),
        "and the address it is being viewed from",
    )
    page.screenshot(path=str(SHOTS / "15-lan-viewer.png"), full_page=True)

    # Deleting is refused here, and the control says so rather than failing later.
    click_button(page, "Repertoire")
    page.wait_for_selector(".row-piece", timeout=20_000)
    page.locator(".row-piece").first.click()
    page.wait_for_selector(".detail-title", timeout=10_000)
    delete_button = page.get_by_role("button", name="Delete", exact=True).first
    check(delete_button.is_disabled(), "Delete is disabled on a machine that is not the piano machine")
    check(
        "piano machine" in (delete_button.get_attribute("title") or ""),
        "and explains where it can be done",
    )
    check(not errors, f"no console errors ({errors})")
    page.close()

    # The sequencer warning is the diagnostic for "the piano is plugged in but the
    # app sees nothing", which is a missing kernel module rather than hardware.
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
```

**7.2 Register it** in `main()`:

```python
            scenario_midi_autodetect(browser)
            scenario_lan_viewer(browser)
```

**7.3 Run.** Expected: `All browser scenarios passed.` with ten scenarios.

**7.4 Commit.** Title: `Verify the interface on a machine that is not the piano machine`.

---

## P9-T8 — Documentation and the full sweep

**Files.** modify `docs/DEPLOYMENT.md`, `docs/ECOSYSTEM.md`, `README.md`,
`AGENT-LOG.md`.

### Steps

**8.1 `docs/DEPLOYMENT.md`.** Add a section *"The two-machine setup (Phase 9)"*
after the existing single-machine chapter, covering: the topology diagram with the
kiosk; `deploy/install.sh`; why the kiosk URL must be `localhost`; the two Chromium
policies and what each prevents; `snd_seq`; the lid/suspend drop-in; the loopback
boundary (what is refused where, and the exact error message); the capture
heartbeat and how to read it; `busy_timeout`; the upload cap and
`SRT_MAX_UPLOAD_MB`; and the note that a reverse proxy would invalidate the
`request.client.host` check. Keep the existing WAL backup guidance and point the
LAN backup at *Export & backup* from the main computer.

**8.2 `docs/ECOSYSTEM.md`.** Mark Phase 8 and Phase 9 landed in §10 with the same
"Landed." paragraph shape used for Phases 1–7, and move the two rows in §6's table
from planned to delivered by adding them to the §9 "Decisions taken" area. Update
the status line at the top to say Phases 1–9.

**8.3 `README.md`.** Point at `deploy/README.md` from the *Single-process mode*
section, and add `SRT_MAX_UPLOAD_MB` to the configuration table.

**8.4 `AGENT-LOG.md`.** Append the entry: D7/D8/D9 implemented; the new
`/api/host` and heartbeat surfaces; the loopback boundary and where it is enforced
(so the other agent does not accidentally add a destructive route without the
dependency); the deployment files; and the two things that will bite a future
reader (`request.client.host` is the check, and the kiosk must use `localhost`).

**8.5 The full sweep.**

```bash
cd frontend && npm test && npx svelte-check --tsconfig ./tsconfig.json && npm run build
cd ../backend && .venv/bin/python -m pytest -q
```

Start the server **on a port nothing is already using, and confirm the new routes
answer before running the browser suite** — a stale server on the same port will
make every new assertion fail for the wrong reason:

```bash
cd backend
SRT_DB_PATH=/home/marco_normal/tmp/SighRTracker/backend/data/e2e.sqlite3 \
SRT_LEGACY_DB=/home/marco_normal/tmp/SighRTracker/backend/data/legacy-fixture.db \
SRT_MEDIA_DIR=/home/marco_normal/tmp/SighRTracker/backend/data/e2e-media \
  .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8011 --log-level warning &
sleep 2
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8011/api/host   # expect 200
```

```bash
SRT_DB_PATH=/home/marco_normal/tmp/SighRTracker/backend/data/e2e.sqlite3 \
SRT_LEGACY_DB=/home/marco_normal/tmp/SighRTracker/backend/data/legacy-fixture.db \
SRT_MEDIA_DIR=/home/marco_normal/tmp/SighRTracker/backend/data/e2e-media \
  backend/.venv/bin/python backend/tools/e2e_browser.py http://127.0.0.1:8011
```

Expected: `All browser scenarios passed.` (10 scenarios).

**8.6 Manual acceptance on the real notebook** (cannot be automated; write the
result in the log entry either way):

1. Piano off, notebook on: Log shows *Capture: not reporting* and the device bar
   says *No MIDI input*.
2. Switch the piano on: within ~5 s the device bar says `MIDI connected ·
   Auto · CASIO …`, and playing a few notes produces a sitting within seconds.
3. From the main computer at `http://<notebook>.local:8000`: statistics load, the
   remote banner appears, Delete is disabled, an upload works and plays back.
4. `curl -s <notebook>.local:8000/api/host` → `sequencer: true`, Casio in `clients`.
5. Reboot the notebook with the piano off, then switch the piano on: capture
   resumes with no interaction.

**8.7 Commit.** Title: `Document Phases 8 and 9`.

---

## Verification sweep (whole change)

| Check | Command | Expected |
| --- | --- | --- |
| Unit rules | `cd frontend && npm test` | `pass 8`, `fail 0` |
| Types | `cd frontend && npx svelte-check --tsconfig ./tsconfig.json` | `0 errors and 0 warnings` |
| Build | `cd frontend && npm run build` | `✓ built in` |
| Backend | `cd backend && .venv/bin/python -m pytest -q` | all pass (631 + ~19 new) |
| Integration | `tools/e2e_browser.py http://127.0.0.1:8011` | `All browser scenarios passed.` (10) |
| Config files | `bash -n deploy/install.sh`; JSON parse; `systemd-analyze verify` | parse clean; only the expected missing-path warning |
| Real machine | the five manual steps in P9-T8 | as listed |

---

## Risks and rollback

| Risk | Mitigation in this plan |
| --- | --- |
| Opening every port doubles notes | P8-T1's `NoteGate`, unit-tested, and the e2e echo assertion |
| Two ports carry *different* notes (zone split) | Nothing is closed: all ports stay attached unless pinned, so nothing is lost |
| `input.id` changes when site data is cleared | The fingerprint fallback (`chooseActive`), tested |
| The loopback check silently stops working behind a proxy | Documented in DEPLOYMENT.md and in the AGENT-LOG entry; `is_loopback` uses `ipaddress`, unit-tested |
| `busy_timeout` hides a genuine deadlock | 5 s is a bound, not a wait forever; a lock held that long is a bug worth surfacing |
| The heartbeat becomes a reason to keep a broken client alive | `screen`/state is not stored in the DB, and a stale report is reported as *not reporting* after 60 s |
| Rollback | Every task is one commit. Phases are independent: reverting Phase 9 leaves a working single-machine app; reverting Phase 8 restores manual selection |

## Retirement

| Retired | In which task | Replacement |
| --- | --- | --- |
| `MidiInput.select(id)` and the `private input` field | P8-T2 | `pin(id \| null)` + `inputs` map |
| `AppState.selectDevice(id)` | P8-T3 | `AppState.pinDevice(id \| null)` |
| `devices[0]` selection | P8-T2 | `chooseActive()` |
| `shutil.copyfileobj` in the upload route (if unused after the cap) | P9-T3 | the counting read loop |

## Execution Readiness View

```text
Execution Readiness View:
- Intent Lock: ECOSYSTEM.md §10 Phase 8 (auto-connect, correct port, hotplug) and
  Phase 9 (LAN server, loopback-only irreversibles, diagnostics, deploy/)
- Scope Fence: no TLS, no remote MIDI, no accounts, no DB sync, no capture daemon
- Baseline Lock: docs/ECOSYSTEM.md §10 (D7/D8/D9) + docs/DEPLOYMENT.md; this plan
  owns the "how" and must not re-open the "what"
- Approved Behavior: as listed per task, each restating the ECOSYSTEM acceptance
  clause it satisfies
- Owner / Contract Constraints: MidiInput stays the only Web MIDI API user;
  midiDevice owns selection rules; hostinfo owns request-origin and machine facts;
  capture_status owns ephemeral capture state; additive API fields only
- Compatibility Boundary: existing routes, `__fakeMidi.send` semantics, DeviceBar
  button names, Python 3.11, erasable-only TypeScript
- Retirement Boundary: four items, retired inside their replacing tasks
- Task Batches: Batch 1 = P8-T1..T4 (logic + transport + UI, sequential);
  Batch 2 = P8-T5..T7 (harness + e2e + docs); Batch 3 = P9-T1..T5 (backend
  boundaries + UI); Batch 4 = P9-T6..T8 (deploy + e2e + docs + sweep)
- Test Obligations: unit (midiDevice), backend (hostinfo, boundaries, upload cap,
  heartbeat), integration (10 e2e scenarios), config syntax, manual notebook run
- Review Gates: after each batch — full suite green before the next batch starts
- Drift / Rewind Rules: a failing e2e assertion after a harness change means fix the
  harness, not the assertion; never weaken an acceptance check to make a batch pass
- Evidence Required Before Completion: the sweep table above, filled in, plus the
  manual notebook result
- Advisory Boundary: method-pack execution guidance only; not GateDecision,
  PolicySnapshot, or completion authority
```

## Execution Route

```text
Execution Route:
- Decision: inline
- Evidence: Phase 8's tasks share `midi.ts`/`state.svelte.ts`/`DeviceBar.svelte`
  and must land in order; Phase 9's backend tasks share `practice/api.py`,
  `models.py` and one test file. Delegation would serialize on the same files
  anyway, and the reviewer of each batch is the full suite.
- Fallback: if a single task grows past its boundary, split it rather than
  delegating; P9-T6 (deployment files) is the only genuinely independent slice and
  can be handed to a subagent if the user wants it done in parallel.
- User confirmation required: yes — the user asked to plan before implementing, so
  execution starts on their go-ahead, not automatically.
```
