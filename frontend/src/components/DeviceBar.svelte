<script lang="ts">
  /**
   * MIDI device state.
   *
   * The list shows *evidence* rather than just names: a port that has never carried
   * a note says so, because on Linux ALSA always exposes a virtual `Midi Through`
   * port that exists and never works. That was the device list that made the app
   * look broken, so the interface now answers the question directly.
   */
  import { app } from '../lib/state.svelte';

  let showLatency = $state(false);
  let draftLatency = $state(app.latencyMs);
  let showPorts = $state(false);

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
      {/if}
    {/if}

    <button class="ghost" onclick={() => { draftLatency = app.latencyMs; showLatency = !showLatency; }}>
      Latency {app.latencyMs} ms
    </button>

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
