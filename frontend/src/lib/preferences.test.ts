import test from 'node:test';
import assert from 'node:assert/strict';
import {
  readBars,
  writeBars,
  readPinnedLevel,
  writePinnedLevel,
  readPinnedHand,
  writePinnedHand,
  readFocus,
  writeFocus,
  readCountInBars,
  writeCountInBars,
  readWeeklyTarget,
  writeWeeklyTarget,
  readClickVolume,
  writeClickVolume,
  readCapture,
  writeCapture,
  readPinnedFingerprint,
  writePinnedFingerprint,
  readStoredLatency,
  writeStoredLatency,
  BAR_CHOICES,
} from './preferences.ts';

// Fake localStorage for Node test runner
const memoryStore = new Map<string, string>();
const fakeLocalStorage = {
  getItem: (key: string) => memoryStore.get(key) ?? null,
  setItem: (key: string, value: string) => memoryStore.set(key, String(value)),
  removeItem: (key: string) => memoryStore.delete(key),
  clear: () => memoryStore.clear(),
};
(globalThis as unknown as { localStorage: typeof fakeLocalStorage }).localStorage = fakeLocalStorage;

test('readBars returns default 4 or validates choices', () => {
  fakeLocalStorage.clear();
  assert.equal(readBars(), 4);
  for (const choice of BAR_CHOICES) {
    writeBars(choice);
    assert.equal(readBars(), choice);
  }
  fakeLocalStorage.setItem('srt.bars', '99');
  assert.equal(readBars(), 4);
});

test('readPinnedLevel validates 1..10 or null', () => {
  fakeLocalStorage.clear();
  assert.equal(readPinnedLevel(), null);
  writePinnedLevel(7);
  assert.equal(readPinnedLevel(), 7);
  writePinnedLevel(null);
  assert.equal(readPinnedLevel(), null);
  fakeLocalStorage.setItem('srt.pinnedLevel', '12');
  assert.equal(readPinnedLevel(), null);
});

test('readPinnedHand validates RH, LH, both or null', () => {
  fakeLocalStorage.clear();
  assert.equal(readPinnedHand(), null);
  writePinnedHand('LH');
  assert.equal(readPinnedHand(), 'LH');
  writePinnedHand(null);
  assert.equal(readPinnedHand(), null);
  fakeLocalStorage.setItem('srt.pinnedHand', 'invalid');
  assert.equal(readPinnedHand(), null);
});

test('readFocus reads boolean flag', () => {
  fakeLocalStorage.clear();
  assert.equal(readFocus(), false);
  writeFocus(true);
  assert.equal(readFocus(), true);
  writeFocus(false);
  assert.equal(readFocus(), false);
});

test('readCountInBars validates 0, 1, 2', () => {
  fakeLocalStorage.clear();
  assert.equal(readCountInBars(), 1);
  writeCountInBars(2);
  assert.equal(readCountInBars(), 2);
  writeCountInBars(0);
  assert.equal(readCountInBars(), 0);
  fakeLocalStorage.setItem('srt.countInBars', '5');
  assert.equal(readCountInBars(), 1);
});

test('readWeeklyTarget validates 1..7 with default 4', () => {
  fakeLocalStorage.clear();
  assert.equal(readWeeklyTarget(), 4);
  writeWeeklyTarget(5);
  assert.equal(readWeeklyTarget(), 5);
  fakeLocalStorage.setItem('srt.weeklyTargetDays', '9');
  assert.equal(readWeeklyTarget(), 4);
});

test('readClickVolume validates 0..127 with default 96', () => {
  fakeLocalStorage.clear();
  assert.equal(readClickVolume(), 96);
  writeClickVolume(110);
  assert.equal(readClickVolume(), 110);
  fakeLocalStorage.setItem('srt.clickVolume', '-10');
  assert.equal(readClickVolume(), 96);
});

test('readCapture defaults to true', () => {
  fakeLocalStorage.clear();
  assert.equal(readCapture(), true);
  writeCapture(false);
  assert.equal(readCapture(), false);
  writeCapture(true);
  assert.equal(readCapture(), true);
});

test('readPinnedFingerprint reads string or null', () => {
  fakeLocalStorage.clear();
  assert.equal(readPinnedFingerprint(), null);
  writePinnedFingerprint('casio-fp');
  assert.equal(readPinnedFingerprint(), 'casio-fp');
  writePinnedFingerprint(null);
  assert.equal(readPinnedFingerprint(), null);
});

test('readStoredLatency clamps between 0 and 500', () => {
  fakeLocalStorage.clear();
  assert.equal(readStoredLatency(), 0);
  writeStoredLatency(45);
  assert.equal(readStoredLatency(), 45);
  fakeLocalStorage.setItem('srt.latencyMs', '999');
  assert.equal(readStoredLatency(), 500);
});
