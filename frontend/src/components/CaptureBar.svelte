<script lang="ts">
  /**
   * Passive capture controls.
   *
   * There is no "record" button in the sense of arming a session: capture is a
   * standing switch, and the backend groups notes into sittings by silence. The
   * counter is here so "is this working?" is answerable without opening the
   * database or playing a chord and hoping.
   */
  import { app } from '../lib/state.svelte';

  const status = $derived(app.captureStatus);

  function toggle(): void {
    app.setCapture(!app.captureEnabled);
  }
</script>

<section class="card capture" data-capture={app.captureEnabled ? 'on' : 'off'}>
  <div class="row wrap">
    <span class="pill" class:good={app.captureEnabled && app.midiConnected}>
      {app.captureEnabled ? 'Logging everything you play' : 'Logging paused'}
    </span>
    {#if !app.midiConnected}
      <span class="pill warn">No MIDI device connected</span>
    {/if}
    <span class="muted small">
      {status.sent} notes sent{#if status.buffered > 0}, {status.buffered} buffered{/if}
    </span>
    {#if status.lastSentAt}
      <span class="muted small mono">last {new Date(status.lastSentAt).toLocaleTimeString()}</span>
    {/if}
    {#if status.lastError}
      <span class="pill bad" title={status.lastError}>
        Not reaching the API — retrying ({status.failed})
      </span>
    {/if}
  </div>

  <div class="row wrap">
    <button onclick={toggle}>
      {app.captureEnabled ? 'Pause logging' : 'Resume logging'}
    </button>
    <button class="ghost" onclick={() => void app.capture.flush()}>Send now</button>
    <span class="muted small">
      Sittings are inferred from silence: play, walk away for five minutes, and the
      log starts a new one.
    </span>
  </div>
</section>

<style>
  .capture {
    display: flex;
    flex-direction: column;
    gap: 0.55rem;
    padding: 0.7rem 0.85rem;
  }

  .small {
    font-size: 0.82rem;
  }
</style>
