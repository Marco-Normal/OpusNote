<script lang="ts">
  import { onDestroy } from 'svelte';
  import { Metronome } from '../lib/metronome';
  import { app } from '../lib/state.svelte';

  /**
   * Latency calibration: play any key exactly on each click. The median offset
   * between your attack and the click is the round-trip delay of your setup, and
   * the scorer subtracts it so a slow rig is not scored as a rhythm error.
   */

  const BPM = 80;
  const CLICKS = 8;
  const COUNT_IN = 4;

  const metronome = new Metronome();

  let running = $state(false);
  let samples = $state<number[]>([]);
  let measured = $state<number | null>(null);
  let unsubscribe: (() => void) | null = null;
  let finishTimer: ReturnType<typeof setTimeout> | null = null;

  // The calibration clicks are plain quarter-note pulses, so the beat unit is 1.
  const secondsPerQuarter = 60 / BPM;

  onDestroy(() => {
    if (finishTimer) clearTimeout(finishTimer);
    unsubscribe?.();
    app.midi.stopRecording();
    metronome.stop();
  });

  async function start(): Promise<void> {
    await metronome.unlock();
    samples = [];
    measured = null;
    running = true;

    const clickTimes: number[] = [];
    metronome.start({
      barsBeats: [CLICKS],
      barBeatUnits: [1],
      secondsPerQuarter,
      countInBeats: COUNT_IN,
    });
    // Onsets are reported relative to beat 1, which is exactly where the first
    // click we score against falls.
    app.midi.startRecording(metronome.downbeatMs);
    for (let index = 0; index < CLICKS; index += 1) {
      clickTimes.push(index * secondsPerQuarter * 1000);
    }

    unsubscribe?.();
    unsubscribe = app.midi.onNote((event) => {
      if (!running) return;
      const timeMs = event.onset * 1000;
      let nearest = Number.POSITIVE_INFINITY;
      for (const click of clickTimes) {
        const distance = timeMs - click;
        if (Math.abs(distance) < Math.abs(nearest)) nearest = distance;
      }
      // Ignore attacks that are nowhere near a click (wrong notes, rests).
      if (Math.abs(nearest) > secondsPerQuarter * 1000 * 0.45) return;
      samples = [...samples, Math.round(nearest)];
    });

    const totalMs = (COUNT_IN + CLICKS) * secondsPerQuarter * 1000;
    finishTimer = setTimeout(() => stop(), totalMs + 600);
  }

  function stop(): void {
    running = false;
    metronome.stop();
    app.midi.stopRecording();
    unsubscribe?.();
    unsubscribe = null;
    if (finishTimer) clearTimeout(finishTimer);
    finishTimer = null;

    if (samples.length === 0) {
      measured = null;
      return;
    }
    const sorted = [...samples].sort((a, b) => a - b);
    const middle = Math.floor(sorted.length / 2);
    const median = sorted.length % 2 === 0 ? (sorted[middle - 1] + sorted[middle]) / 2 : sorted[middle];
    measured = Math.round(median);
  }

  function apply(): void {
    if (measured === null) return;
    app.setLatency(measured);
    measured = null;
    samples = [];
  }
</script>

<div class="calibrator">
  <div class="spread wrap">
    <div>
      <h3>Input latency</h3>
      <p class="muted small">
        Play any key exactly on each of {CLICKS} clicks. We take the median offset. Currently
        subtracting <b class="mono">{app.latencyMs} ms</b>.
      </p>
    </div>
    <div class="row">
      {#if running}
        <button onclick={stop}>Stop</button>
        <span class="pill mono">{samples.length} hits</span>
      {:else}
        <button class="primary" onclick={() => void start()}>Measure</button>
      {/if}
    </div>
  </div>

  {#if samples.length > 0}
    <div class="row wrap hits">
      {#each samples as sample, index (index)}
        <span class="pill mono" class:good={Math.abs(sample) < 60} class:warn={Math.abs(sample) >= 60}>
          {sample > 0 ? '+' : ''}{sample} ms
        </span>
      {/each}
    </div>
  {/if}

  {#if measured !== null}
    <div class="row wrap measured">
      <span class="pill accent mono">median {measured > 0 ? '+' : ''}{measured} ms</span>
      <button class="primary" onclick={apply}>Use {measured} ms</button>
      <button class="ghost" onclick={() => (measured = null)}>Dismiss</button>
    </div>
  {/if}
</div>

<style>
  .calibrator {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    border: 1px solid var(--line);
    border-radius: var(--radius);
    background: var(--surface-2);
    padding: 0.6rem 0.75rem;
  }

  p {
    margin: 0.15rem 0 0;
    max-width: 62ch;
    line-height: 1.5;
  }

  .small {
    font-size: 0.82rem;
  }

  .hits {
    max-height: 5rem;
    overflow-y: auto;
  }

  .measured {
    border-top: 1px solid var(--line);
    padding-top: 0.5rem;
  }
</style>
