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

test('a port that has carried a note beats the name hint', () => {
  const activity = new PortActivity();
  activity.note(through.id, 1_000);
  assert.equal(
    chooseActive([through, casio], { activity }),
    through.id,
    'evidence wins even when it contradicts the name',
  );
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
  assert.equal(
    chooseActive(ports),
    casio.id,
    'before the first note: the port that is not called Midi Through',
  );
  assert.equal(
    chooseActive([through]),
    through.id,
    'and with nothing else present, even the silent-looking port is used',
  );

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
