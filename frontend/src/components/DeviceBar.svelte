<script lang="ts">
  import { app } from '../lib/state.svelte';

  let showLatency = $state(false);
  let draftLatency = $state(app.latencyMs);

  function saveLatency() {
    app.setLatency(draftLatency);
    showLatency = false;
  }
</script>

<section class="card bar">
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

    {#if app.midiSupported}
      {#if app.devices.length > 0}
        <label class="device">
          <span class="muted">Device</span>
          <select
            value={app.selectedDeviceId ?? ''}
            onchange={(event) => app.selectDevice((event.currentTarget as HTMLSelectElement).value)}
          >
            {#each app.devices as device (device.id)}
              <option value={device.id}>{device.name}</option>
            {/each}
          </select>
        </label>
      {/if}
      <button onclick={() => app.connectMidi()}>
        {app.devices.length > 0 ? 'Rescan' : 'Connect MIDI'}
      </button>
    {/if}

    <button class="ghost" onclick={() => { draftLatency = app.latencyMs; showLatency = !showLatency; }}>
      Latency {app.latencyMs} ms
    </button>
  </div>

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
    background: #c4c4bd;
  }

  .dot.on {
    background: var(--good);
  }

  .device {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    font-size: 0.85rem;
  }

  .latency {
    border-top: 1px solid var(--line);
    padding-top: 0.5rem;
  }

  .small {
    font-size: 0.82rem;
  }
</style>
