<script lang="ts">
  /**
   * The device bar's first tier: the one line that is always on screen.
   *
   * It shows what you have to *notice* and what is blocked right now, and nothing else.
   * Everything you configure — ports, pedals, latency, count-in, click, playback instrument —
   * moved into `SetupPanel`, because ten controls in a permanent strip is a bar you stop
   * reading. The split is deliberate: state stays, configuration goes.
   *
   * Three things deliberately stayed here rather than moving into the drawer:
   *
   * * **the take switch**, because capture is a standing switch rather than a per-sitting
   *   button, so both its position and its failure modes must be visible without a click —
   *   the trap the whole module exists to avoid is a switch that looks armed and records
   *   nothing;
   * * **the audio state**, because `suspended` is the single most common cause of "it is not
   *   making any sound" and it is invisible everywhere else;
   * * **the latency suggestion**, because it is an *offer*, and an offer inside a closed
   *   drawer is not an offer.
   */
  import { app } from '../lib/state.svelte';

  let { onsetup }: { onsetup: () => void } = $props();

  const activeName = $derived(app.ports.find((port) => port.id === app.midiActiveId)?.name ?? null);

  const suggested = $derived(app.latencySuggestionMs);
  const worthSuggesting = $derived(suggested !== null && Math.abs(suggested - app.latencyMs) >= 25);
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

    {#if app.midiSupported && !app.midiConnected}
      <button onclick={() => void app.connectMidi()}>Connect MIDI</button>
    {/if}

    <!--
      The take switch. It asks the server for the segment gap every time it is armed, so a
      take is cut where the notes are cut rather than at a constant copied here.
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
        microphone ready
      </span>
    {:else if app.audioDevice === 'unavailable'}
      <span class="pill bad" data-audio-device="unavailable">
        no audio input on this machine — nothing can be recorded
      </span>
    {:else if app.audioDevice === 'denied'}
      <span class="pill bad" data-audio-device="denied">
        the browser refused the microphone
      </span>
    {/if}
    {#if app.takesCaptured > 0}
      <span class="muted small" data-takes-captured={app.takesCaptured}>
        {app.takesCaptured} take{app.takesCaptured === 1 ? '' : 's'}
      </span>
    {/if}

    <!-- Why the switch refused, when it refuses. This belongs beside the switch rather than
         in Setup: "it will not arm" with no reason visible is the failure this control
         exists to prevent. -->
    {#if app.audioNote}
      <span class="muted small" data-audio-note>{app.audioNote}</span>
    {/if}

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

    <button class="ghost setup-trigger" data-setup-trigger onclick={onsetup}>
      <svg class="icon" viewBox="0 0 24 24" aria-hidden="true">
        <circle cx="12" cy="12" r="3.1" />
        <path
          d="M19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-1.8-.3 1.6 1.6 0 0 0-1 1.5v.2a2 2 0 1 1-4 0v-.1a1.6 1.6 0 0 0-1-1.5 1.6 1.6 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.6 1.6 0 0 0 .3-1.8 1.6 1.6 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.6 1.6 0 0 0 1.5-1 1.6 1.6 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.6 1.6 0 0 0 1.8.3H9a1.6 1.6 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.6 1.6 0 0 0 1 1.5 1.6 1.6 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0-.3 1.8V9a1.6 1.6 0 0 0 1.5 1h.2a2 2 0 1 1 0 4h-.1a1.6 1.6 0 0 0-1.5 1z"
        />
      </svg>
      Setup
    </button>
  </div>
</section>

<style>
  .bar {
    padding: 0.5rem 0.7rem;
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

  .setup-trigger {
    margin-left: auto;
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
  }

  .icon {
    width: 0.95rem;
    height: 0.95rem;
    fill: none;
    stroke: currentColor;
    stroke-width: 1.6;
    stroke-linecap: round;
    stroke-linejoin: round;
  }

  .small {
    font-size: 0.82rem;
  }
</style>
