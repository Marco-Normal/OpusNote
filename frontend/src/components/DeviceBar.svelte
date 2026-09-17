<script lang="ts">
  /**
   * MIDI device state.
   *
   * The list shows *evidence* rather than just names: a port that has never carried
   * a note says so, because on Linux ALSA always exposes a virtual `Midi Through`
   * port that exists and never works. That was the device list that made the app
   * look broken, so the interface now answers the question directly.
   */
  import { onMount } from 'svelte';
  import { app } from '../lib/state.svelte';

  let showLatency = $state(false);
  let draftLatency = $state(app.latencyMs);
  let showPorts = $state(false);
  let showPedals = $state(false);

  /** The three pedals a piano may send, and whether this one has. */
  const PEDALS: { cc: number; label: string }[] = [
    { cc: 64, label: 'Damper (right)' },
    { cc: 66, label: 'Sostenuto (middle)' },
    { cc: 67, label: 'Soft (left)' },
  ];

  function pedalState(cc: number): string {
    return app.seenControllers.includes(cc) ? 'sends this' : 'not seen yet';
  }

  /**
   * What playback comes out of.
   *
   * Three answers, because they suit three situations: the piano itself when one is
   * connected (the only genuinely real piano sound), the sampled piano when it has
   * been downloaded, and the built-in synthesiser otherwise. The choice lives here
   * rather than in the Log view because it applies to every play button in the app.
   */
  onMount(() => {
    void app.refreshPiano();
  });

  /**
   * A latency suggestion, when your own timing has consistently said so.
   *
   * Never applied on its own: the number corrects for the delay of a keyboard, a
   * browser and a sound card, and silently changing what the scorer subtracts would
   * make every past score incomparable with the next one.
   */
  const suggested = $derived(app.latencySuggestionMs);
  const worthSuggesting = $derived(
    suggested !== null && Math.abs(suggested - app.latencyMs) >= 25,
  );

  // A once-a-second clock, so "last note 3 s ago" ticks without the store having to
  // tick with it.
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
        {app.midiPinned ? 'Pinned' : 'Auto'} · {activeName}
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
        <button class="ghost tiny" data-pedals-trigger onclick={() => (showPedals = !showPedals)}>
          Pedals
        </button>
      {/if}
    {/if}

    <button class="ghost" onclick={() => { draftLatency = app.latencyMs; showLatency = !showLatency; }}>
      Latency {app.latencyMs} ms
    </button>

    <span class="row sound">
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
    </span>

    <span class="row sound">
      <label class="muted small" for="click-volume">Click</label>
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
    </span>

    <!--
      The audio switch. It asks the server for the segment gap every time it is armed,
      so a take is cut where the notes are cut rather than at a constant copied here.
      The readout below is not decoration: a machine with no input, a refused
      permission and a working microphone are three different facts, and the failure
      it avoids is a switch that looks armed and records nothing.
    -->
    <button
      class="ghost"
      data-audio-capture={app.audioArmed ? 'armed' : 'off'}
      onclick={() => void app.toggleAudioCapture()}
    >
      {app.audioArmed ? 'Recording takes' : 'Record takes'}
    </button>
    {#if app.audioArmed}
      <span class="pill good" data-audio-device="ready">
        microphone ready · mono Opus, about 14 MB/hour
      </span>
    {:else if app.audioDevice === 'unavailable'}
      <span class="pill bad" data-audio-device="unavailable">
        no audio input on this machine — nothing can be recorded
      </span>
    {:else if app.audioDevice === 'denied'}
      <span class="pill bad" data-audio-device="denied">
        the browser refused the microphone; on the piano machine the kiosk policy grants it
      </span>
    {/if}
    {#if app.takesCaptured > 0}
      <span class="muted small" data-takes-captured={app.takesCaptured}>
        {app.takesCaptured} take{app.takesCaptured === 1 ? '' : 's'} recorded
      </span>
    {/if}
    {#if app.audioNote}
      <span class="muted small" data-audio-note>{app.audioNote}</span>
    {/if}

    <span
  class="row sound"
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
      {#if app.audioState !== 'running'}
        <!-- The one fact that explains silence with no error: a suspended audio
             context plays nothing and reports nothing. -->
        <span
          class="pill warn"
          data-audio-state={app.audioState}
          title="A browser may only start audio after a click on the page"
        >
          audio {app.audioState}
        </span>
      {:else}
        <span class="muted small mono" data-audio-state="running">audio ok</span>
      {/if}
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
    </span>

    {#if worthSuggesting}
      <button
        class="ghost tiny"
        data-latency-suggestion={Math.round(suggested ?? 0)}
        title="Your recent attempts are consistently early or late by this much"
        onclick={() => app.setLatency(Math.max(0, Math.round(suggested ?? 0)))}
      >
        Use {Math.round(suggested ?? 0)} ms
      </button>
    {/if}
  </div>

  {#if app.midiConnected && app.midiPinned}
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

  {#if showPedals}
    <div class="row wrap latency" data-pedals>
      <span class="muted small">
        Press each pedal once. A pedal the piano does not send cannot be bound to anything,
        so this is a report rather than a promise. One press of the sostenuto arms the
        recording, and another stops it; two taps of the damper in silence start or finish a
        workout.
      </span>
      {#each PEDALS as pedal (pedal.cc)}
        <span
          class="pill"
          class:good={app.seenControllers.includes(pedal.cc)}
          data-pedal={pedal.cc}
        >
          {pedal.label} · CC{pedal.cc} · {pedalState(pedal.cc)}
        </span>
      {/each}
      {#if app.pedalActionNote}
        <span class="muted small" data-pedal-note>{app.pedalActionNote}</span>
      {/if}
    </div>
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
