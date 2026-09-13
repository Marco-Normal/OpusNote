<script lang="ts">
  /**
   * "Hear it": the player controls, once.
   *
   * Two places want this — the panel after an attempt, and a past attempt opened from
   * the history — and they differ only in where the notes come from. Keeping one owner
   * means the handle/progress/stop behaviour cannot drift between them.
   */
  import { onDestroy } from 'svelte';
  import { PianoPlayer } from '../lib/pianoPlayer';
  import { forHands, type Hand, type SynthNote } from '../lib/playback';

  interface Props {
    /** What was played, with hands recovered from the score where possible. */
    attempt: readonly SynthNote[];
    /** The same music as notated, at the tempo it was counted in at. */
    written: readonly SynthNote[];
    /** Somewhere to say what this particular source is, e.g. "synthesised". */
    caption?: string;
  }

  let { attempt, written, caption = 'Synthesised, not the piano — but the timing and touch are yours.' }: Props = $props();

  const player = new PianoPlayer();
  let playing = $state<'mine' | 'written' | null>(null);
  let hearRight = $state(true);
  let hearLeft = $state(true);
  let progress = $state(0);

  const hands = $derived(
    [hearRight ? 'RH' : null, hearLeft ? 'LH' : null].filter(Boolean) as Hand[],
  );
  const mine = $derived(forHands(attempt, hands));
  const score = $derived(forHands(written, hands));

  async function hear(source: 'mine' | 'written'): Promise<void> {
    const notes = source === 'mine' ? mine : score;
    if (notes.length === 0) return;
    playing = source;
    progress = 0;
    await player.play(notes, {
      onProgress: (handle) => {
        progress = handle.total > 0 ? Math.min(1, handle.elapsed / handle.total) : 0;
      },
      onDone: () => {
        playing = null;
        progress = 0;
      },
    });
  }

  function stop(): void {
    player.stop();
    playing = null;
    progress = 0;
  }

  onDestroy(() => player.dispose());
</script>

<div class="row wrap hearing" data-playing={playing ?? 'false'}>
  <span class="muted small">Hear it</span>
  <button class="ghost" onclick={() => void hear('mine')} disabled={mine.length === 0}>
    Play yours
  </button>
  <button class="ghost" onclick={() => void hear('written')} disabled={score.length === 0}>
    Play as written
  </button>
  {#if playing}
    <button class="ghost" onclick={stop}>Stop</button>
  {/if}
  <label class="hand">
    <input type="checkbox" bind:checked={hearRight} /> RH
  </label>
  <label class="hand">
    <input type="checkbox" bind:checked={hearLeft} /> LH
  </label>
  {#if playing}
    <span class="meter" aria-hidden="true"><span style="width: {progress * 100}%"></span></span>
  {/if}
  <span class="muted small">{caption}</span>
</div>

<style>
  .hearing {
    border-top: 1px solid var(--line);
    padding-top: 0.6rem;
    align-items: center;
  }

  .hand {
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
    font-size: 0.82rem;
    color: var(--muted);
  }

  .meter {
    flex: 0 0 6rem;
    height: 3px;
    border-radius: 999px;
    background: var(--track);
    overflow: hidden;
  }

  .meter span {
    display: block;
    height: 100%;
    background: var(--accent);
  }
</style>
