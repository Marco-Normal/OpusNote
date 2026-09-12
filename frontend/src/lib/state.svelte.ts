/**
 * Shared application state.
 *
 * A single runes-based store keeps the MIDI device, profile, and latency
 * calibration in one place so every view reads the same values.
 */

import { api } from './api';
import { MidiInput, type MidiDeviceInfo } from './midi';
import type { AppView, Profile } from './types';

const LATENCY_STORAGE_KEY = 'srt.latencyMs';

function readStoredLatency(): number {
  try {
    const raw = localStorage.getItem(LATENCY_STORAGE_KEY);
    const value = raw === null ? 0 : Number(raw);
    return Number.isFinite(value) ? Math.max(0, Math.min(500, value)) : 0;
  } catch {
    return 0;
  }
}

class AppState {
  view = $state<AppView>('practice');

  /** One MIDI input shared by every view; connecting twice would double events. */
  readonly midi = new MidiInput();

  midiSupported = $state(MidiInput.isSupported());
  midiConnected = $state(false);
  midiError = $state<string | null>(null);
  devices = $state<MidiDeviceInfo[]>([]);
  selectedDeviceId = $state<string | null>(null);

  latencyMs = $state(readStoredLatency());

  profile = $state<Profile | null>(null);
  apiOnline = $state<boolean | null>(null);
  errorMessage = $state<string | null>(null);

  /** Bumped whenever a performance is recorded, so Stats can refetch. */
  revision = $state(0);

  setLatency(value: number): void {
    const clamped = Math.max(0, Math.min(500, Math.round(value)));
    this.latencyMs = clamped;
    try {
      localStorage.setItem(LATENCY_STORAGE_KEY, String(clamped));
    } catch {
      // Storage may be unavailable (private mode); the in-memory value still works.
    }
  }

  async bootstrap(): Promise<void> {
    try {
      await api.health();
      this.apiOnline = true;
      this.errorMessage = null;
    } catch (error) {
      this.apiOnline = false;
      this.errorMessage = error instanceof Error ? error.message : String(error);
      return;
    }
    await this.refreshProfile();
  }

  async refreshProfile(): Promise<void> {
    try {
      this.profile = await api.profile();
    } catch (error) {
      this.errorMessage = error instanceof Error ? error.message : String(error);
    }
  }

  async connectMidi(): Promise<void> {
    this.midiError = null;
    try {
      const devices = await this.midi.connect();
      this.devices = devices;
      this.selectedDeviceId = this.midi.selectedId;
      this.midiConnected = devices.length > 0;
      if (devices.length === 0) {
        this.midiError =
          'No MIDI input found. Connect the PX-870 over USB, make sure it is powered on, then rescan.';
      }
      this.midi.onDevices((next) => {
        this.devices = next;
        if (!this.selectedDeviceId && next.length > 0) {
          this.selectDevice(next[0].id);
        }
      });
    } catch (error) {
      this.midiConnected = false;
      this.midiError = error instanceof Error ? error.message : String(error);
    }
  }

  selectDevice(id: string): void {
    try {
      this.midi.select(id);
      this.selectedDeviceId = id;
      this.midiConnected = true;
      this.midiError = null;
    } catch (error) {
      this.midiError = error instanceof Error ? error.message : String(error);
    }
  }
}

export const app = new AppState();
