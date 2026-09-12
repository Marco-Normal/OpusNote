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
    <strong>ALSA's sequencer is not present on this machine.</strong>
    MIDI inputs will not appear, whatever is plugged in, until <code>snd_seq</code> is
    loaded — see <code>docs/DEPLOYMENT.md</code>.
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
