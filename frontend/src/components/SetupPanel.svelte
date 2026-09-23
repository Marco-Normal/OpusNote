<script lang="ts">
  /**
   * Setup: everything you configure, in one place, behind one button.
   *
   * This holds what used to be the device bar's second and third rows — ports, pedals,
   * latency, count-in, click volume, playback instrument and the capture diagnostics. Ten
   * controls in a permanent strip is a bar you stop reading, and the four that matter were
   * lost among the six that do not.
   *
   * It is a disclosure rather than a modal overlay: the app has exactly one of those (the
   * command palette) and adding a second would mean a second z-index, a second scrim and a
   * second Escape rule to keep in step. Nothing here is urgent enough to justify that.
   */
  import { onMount } from 'svelte';
  import { app } from '../lib/state.svelte';
  import { HAND_CHOICES, HAND_LABELS, type HandChoice } from '../lib/types';
  import {
    ACTION_LABELS,
    ACTION_SHORT,
    GESTURE_LABELS,
    HANDSFREE_ACTIONS,
    PEDAL_GESTURE_KINDS,
  } from '../lib/pedalBindings';
  import type { HandsfreeAction } from '../lib/pedalGesture';

  let { onclose }: { onclose: () => void } = $props();

  let draftLatency = $state(app.latencyMs);

  /**
   * The three pedals a piano may send, and whether this one has.
   *
   * The binding is printed beside the discovery for one reason: two of the three pedals are
   * deliberately bound to nothing, because they are played — and a pedal that silently does
   * nothing is indistinguishable from a broken feature unless the panel says which it is.
   * CC66's line is read from the live preference, so what it prints is what the pedal does.
   */
  const PEDALS: { cc: number; label: string }[] = [
    { cc: 64, label: 'Damper (right)' },
    { cc: 66, label: 'Sostenuto (middle)' },
    { cc: 67, label: 'Soft (left)' },
  ];

  /** What CC66's gestures carry, in the few words that fit beside the discovery report. */
  function bindingSummary(cc: number): string {
    if (cc !== 66) return 'deliberately not bound';
    const parts: string[] = [];
    for (const kind of PEDAL_GESTURE_KINDS) {
      const action = app.pedalBindings[kind];
      if (action !== null) parts.push(`${GESTURE_LABELS[kind]}: ${ACTION_SHORT[action]}`);
    }
    // A pedal with nothing bound must say so rather than read as broken: this is the sentence
    // that makes "the pedal does nothing" answerable by looking.
    return parts.length === 0 ? 'nothing bound' : parts.join(' · ');
  }

  function pedalState(cc: number): string {
    return app.seenControllers.includes(cc) ? 'sends this' : 'not seen yet';
  }

  onMount(() => {
    void app.refreshPiano();
  });

  // A once-a-second clock, so "last note 3 s ago" ticks without the store having to
  // tick with it.
  let nowMs = $state(Date.now());
  $effect(() => {
    const timer = setInterval(() => (nowMs = Date.now()), 1_000);
    return () => clearInterval(timer);
  });

  function portNote(portId: string): string {
    const port = app.ports.find((item) => item.id === portId);
    if (!port || port.notes === 0 || port.lastNoteMs === null) return 'no notes yet';
    const seconds = Math.max(0, Math.round((nowMs - port.lastNoteMs) / 1000));
    const ago = seconds < 60 ? `${seconds} s ago` : `${Math.round(seconds / 60)} min ago`;
    return `${port.notes} notes · last ${ago}`;
  }

  function saveLatency() {
    app.setLatency(draftLatency);
  }

  /** Calibration is a full view with exercises in it, so it stays a page — reached from here
   *  rather than competing for a tab of its own. */
  function openCalibration() {
    onclose();
    app.navigate({ name: 'calibrate' });
  }
</script>

<section class="card setup" data-setup aria-label="Setup">
  <header class="setup-head">
    <h2>Setup</h2>
    <button class="ghost tiny" onclick={onclose}>Close</button>
  </header>

  <div class="group" data-setup-devices>
    <h3>Devices</h3>
    {#if app.midiSupported && app.ports.length === 0}
      <p class="muted small">
        No MIDI input is visible yet. Plug the piano in and press Connect MIDI.
      </p>
    {/if}
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
    <div class="row wrap">
      {#if app.midiSupported}
        <button onclick={() => void app.connectMidi()}>
          {app.devices.length > 0 ? 'Rescan MIDI' : 'Connect MIDI'}
        </button>
      {/if}
      {#if app.midiConnected && app.midiPinned}
        <button class="ghost tiny" onclick={() => app.pinDevice(null)}>
          Back to automatic selection
        </button>
      {/if}
    </div>
    {#if app.midiNeedsGesture}
      <p class="muted small">
        The browser wants a click before it will hand over MIDI access. On the piano machine
        this is granted automatically; press Connect MIDI once and it is remembered.
      </p>
    {/if}
    {#if app.midiError}
      <p class="error-banner small">{app.midiError}</p>
    {/if}
  </div>

  <div class="group" data-pedals>
    <h3>Pedals</h3>
    <p class="muted small">
      Press each pedal once. A pedal the piano does not send cannot be bound to anything, so this
      is a report rather than a promise. The sostenuto carries three gestures, each bound to one
      action or to nothing. Left as shipped: a single press flags the place for review, a double
      press starts or finishes a workout, and a press and hold arms or stops take recording — so
      stopping a take needs a deliberate hold rather than a tap. The damper and the soft pedal are
      bound to nothing at all: both are played, and a press mid-phrase must never end a take.
    </p>
    <div class="row wrap">
      {#each PEDALS as pedal (pedal.cc)}
        <span
          class="pill"
          class:good={app.seenControllers.includes(pedal.cc)}
          data-pedal={pedal.cc}
        >
          {pedal.label} · CC{pedal.cc} · {bindingSummary(pedal.cc)} · {pedalState(pedal.cc)}
        </span>
      {/each}
    </div>
    <div class="row wrap" data-pedal-bindings>
      {#each PEDAL_GESTURE_KINDS as kind (kind)}
        <label class="muted small" for="pedal-{kind}">{GESTURE_LABELS[kind]}</label>
        <select
          id="pedal-{kind}"
          data-pedal-binding={kind}
          value={app.pedalBindings[kind] ?? ''}
          onchange={(event) => {
            const raw = (event.currentTarget as HTMLSelectElement).value;
            app.setPedalBinding(kind, raw === '' ? null : (raw as HandsfreeAction));
          }}
        >
          <option value="">nothing</option>
          {#each HANDSFREE_ACTIONS as action (action)}
            <option value={action}>{ACTION_LABELS[action]}</option>
          {/each}
        </select>
      {/each}
    </div>
    {#if app.pedalActionNote}
      <span class="muted small" data-pedal-note>{app.pedalActionNote}</span>
    {/if}
  </div>

  <div class="group" data-setup-timing>
    <h3>Timing</h3>
    <p class="muted small">
      Latency is the measured round-trip delay of your setup. It is subtracted from every note
      before scoring, so changing it makes past scores incomparable — which is why nothing
      changes it for you.
    </p>
    <div class="row wrap">
      <label class="muted small" for="latency">Latency</label>
      <input id="latency" type="number" min="0" max="500" step="5" bind:value={draftLatency} />
      <span class="muted small">ms</span>
      <button class="primary" onclick={saveLatency}>Save</button>
      <button class="ghost" onclick={() => (draftLatency = 0)}>Reset</button>
      <button class="ghost" data-calibrate-link onclick={openCalibration}>
        Calibrate by playing…
      </button>
    </div>
    <div class="row wrap">
      <label class="muted small" for="count-in">Count-in</label>
      <select
        id="count-in"
        value={app.countInBars}
        onchange={(event) =>
          app.setCountInBars(Number((event.currentTarget as HTMLSelectElement).value))}
      >
        <option value={0}>none</option>
        <option value={1}>1 bar</option>
        <option value={2}>2 bars</option>
      </select>
      <span class="muted small">bars of click before a run starts</span>
    </div>
  </div>

  <div class="group" data-setup-reading>
    <h3>What you read</h3>
    <p class="muted small">
      Left alone, the difficulty comes from your ratings, and it also decides which hand you
      read — level 1 is the right hand, level 2 the left, and 3 upward both. Pinning either
      one hands you the choice: read the bass clef with easy material, or the right hand with
      hard. <strong>A pinned exercise is scored and logged, and does not change your
      ratings</strong> — you chose the material, so it is not an assessment of you. Both
      settings clear with the × beside them in Practice.
    </p>
    <div class="row wrap">
      <label class="muted small" for="pinned-level">Difficulty</label>
      <select
        id="pinned-level"
        value={app.pinnedLevel === null ? '' : String(app.pinnedLevel)}
        onchange={(event) => {
          const raw = (event.currentTarget as HTMLSelectElement).value;
          app.setPinnedLevel(raw === '' ? null : Number(raw));
        }}
      >
        <option value="">from my ratings</option>
        {#each Array.from({ length: 10 }, (_, index) => index + 1) as level (level)}
          <option value={String(level)}>level {level}</option>
        {/each}
      </select>
      <label class="muted small" for="pinned-hand">Hands</label>
      <select
        id="pinned-hand"
        value={app.pinnedHand ?? ''}
        onchange={(event) => {
          const raw = (event.currentTarget as HTMLSelectElement).value;
          app.setPinnedHand(raw === '' ? null : (raw as HandChoice));
        }}
      >
        <option value="">from the difficulty</option>
        {#each HAND_CHOICES as choice (choice)}
          <option value={choice}>{HAND_LABELS[choice]}</option>
        {/each}
      </select>
    </div>
  </div>

  <div class="group" data-setup-sound>
    <h3>Sound</h3>
    <div class="row wrap">
      <label class="muted small" for="click-volume">Click volume</label>
      <input
        id="click-volume"
        type="range"
        min="0"
        max="127"
        step="1"
        value={app.clickVolume}
        aria-label="Metronome click volume"
        oninput={(event) =>
          app.setClickVolume(Number((event.currentTarget as HTMLInputElement).value))}
      />
    </div>
    <div
      class="row wrap"
      data-sound
      data-instrument={app.instrument}
      data-sample-state={app.sampleState}
    >
      <label class="muted small" for="instrument">Playback</label>
      <!-- Explicit value and onchange rather than `bind:`, so the choice goes through
           the store: the store also tells the shared player and remembers it. -->
      <select
        id="instrument"
        value={app.instrument}
        onchange={(event) => {
          const value = (event.currentTarget as HTMLSelectElement).value;
          if (value === 'midi' || value === 'piano' || value === 'synth') {
            void app.setInstrument(value);
          }
        }}
      >
        <option value="midi" disabled={app.outputs.length === 0}>
          Through the piano{app.outputs.length === 0 ? ' (none connected)' : ''}
        </option>
        <option value="piano" disabled={!app.piano?.available}>
          Sampled piano{app.piano?.available ? '' : ' (not installed)'}
        </option>
        <option value="synth">Synthesiser</option>
      </select>
      {#if app.instrument === 'piano' && !app.piano?.available}
        <button
          class="ghost tiny"
          data-install-piano
          disabled={app.downloadingPiano}
          onclick={() => void app.downloadPiano()}
        >
          {app.downloadingPiano ? 'Downloading…' : 'Install (2 MB, once)'}
        </button>
      {/if}
      {#if app.instrument === 'piano' && app.piano && !app.piano.available && app.piano.present > 0}
        <span class="muted small">
          {app.piano.present}/{app.piano.total} samples — try again
        </span>
      {/if}
      <button
        class="ghost tiny"
        data-test-sound
        disabled={app.testingSound}
        title="Play a short chord through the instrument above"
        onclick={() => void app.testSound()}
      >
        {app.testingSound ? 'Playing…' : 'Test'}
      </button>
    </div>
    <p class="muted small">
      The sampled piano is a one-time 2 MB download, served from this machine afterwards.
      Nothing at play time touches the network.
    </p>
    {#if app.soundError}
      <span class="pill bad" data-sound-error={app.soundError}>{app.soundError}</span>
    {/if}
    {#if app.sampleState === 'loading'}
      <span class="muted small" data-sample-loading>loading samples…</span>
    {/if}
    {#if app.instrument === 'piano' && app.pianoError}
      <!-- Falling back to the synthesiser is right; doing it silently is not, and
           made a sample set that would not decode look like a wrong setting. -->
      <span class="pill bad" data-sample-error={app.pianoError} title={app.pianoError}>
        samples failed to load — using the synthesiser
      </span>
    {/if}
  </div>

  <div class="group" data-setup-capture>
    <h3>Capture</h3>
    <p class="muted small">
      Takes are mono Opus at about 14 MB an hour — a convenience rather than an archive; the
      piano's own recording to a USB stick is still the one to keep. A take opens on the first
      note and closes when you have stopped for as long as the server treats as a segment
      boundary, so silence is not stored. Arm the switch in the device bar.
    </p>
  </div>
</section>

<style>
  .setup {
    padding: 0.9rem 1rem;
    display: flex;
    flex-direction: column;
    gap: 1.1rem;
  }

  .setup-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
  }

  .group {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    border-top: 1px solid var(--line);
    padding-top: 0.75rem;
  }

  .group:first-of-type {
    border-top: none;
    padding-top: 0;
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

  .small {
    font-size: 0.82rem;
  }
</style>
