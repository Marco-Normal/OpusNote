<script lang="ts">
  /**
   * The playback transport controls for the sitting timeline:
   * Play sitting, Play from here, Stop, segment stepping, 30s scrubbing jumps,
   * clock position, and falling notes toggle.
   */
  import { app } from '../lib/state.svelte';
  import { formatClock } from '../lib/clock';

  interface Props {
    playing: { fromMs: number; toMs: number; segmentId: number | null } | null;
    noteCount: number;
    segmentsCount: number;
    durationS: number;
    position: number;
    total: number;
    showRoll: boolean;
    onStop: () => void;
    onPlaySitting: () => void;
    onPlayFromHere: () => void;
    onStepSegment: (direction: -1 | 1) => void;
    onJump: (deltaSeconds: number) => void;
  }

  let {
    playing,
    noteCount,
    segmentsCount,
    durationS,
    position,
    total,
    showRoll = $bindable(false),
    onStop,
    onPlaySitting,
    onPlayFromHere,
    onStepSegment,
    onJump,
  }: Props = $props();
</script>

<div class="row wrap transport" data-playing={playing ? 'true' : 'false'}>
  {#if playing}
    <button class="ghost tiny" data-stop onclick={onStop}>Stop</button>
    <span class="muted small">
      Playing {playing.segmentId === null ? 'the sitting' : 'this segment'}
    </span>
  {:else}
    <button
      class="ghost tiny"
      disabled={noteCount === 0}
      onclick={onPlaySitting}
    >
      Play the sitting
    </button>
    <!-- Always present, disabled until there is somewhere to start from: a button that
         appeared on the first drag would reflow the row above the strip and move the strip
         out from under the pointer mid-scrub. -->
    <button
      class="ghost tiny"
      data-play-from-here
      disabled={noteCount === 0 || position <= 0 || position >= total - 1}
      title="Play from where the playhead is, to the end of the sitting"
      onclick={onPlayFromHere}
    >
      ▶ From here
    </button>
  {/if}

  <span class="row jump">
    <button
      class="ghost tiny"
      data-step-segment-back
      disabled={noteCount === 0 || segmentsCount === 0}
      title="Back to the start of this segment, or to the previous one"
      onclick={() => onStepSegment(-1)}
    >
      « segment
    </button>
    <button
      class="ghost tiny"
      data-step-segment-forward
      disabled={noteCount === 0 || segmentsCount === 0}
      title="On to the start of the next segment"
      onclick={() => onStepSegment(1)}
    >
      segment »
    </button>
  </span>

  <span class="row jump">
    <button class="ghost tiny" disabled={noteCount === 0} onclick={() => onJump(-30)}>
      « 30 s
    </button>
    <button class="ghost tiny" disabled={noteCount === 0} onclick={() => onJump(30)}>
      30 s »
    </button>
  </span>

  <span class="pill mono" data-position>{formatClock(position / 1000)} / {formatClock(durationS)}</span>

  <label class="row toggle">
    <input type="checkbox" bind:checked={showRoll} data-roll-toggle />
    Falling notes
  </label>

  <span class="muted small">
    Press or drag the strip to move through the sitting — silent until something is playing, and
    a press while listening carries the sound with it.
    Played through
    {app.instrument === 'midi'
      ? 'the piano itself'
      : app.instrument === 'piano'
        ? 'the sampled piano'
        : 'the synthesiser'}
    — timing and touch are yours.
  </span>
</div>

<style>
  .transport {
    align-items: center;
    gap: 0.6rem;
    padding: 0.4rem 0.6rem;
    border: 1px solid var(--line);
    border-radius: var(--radius);
    background: var(--surface-2);
  }

  .jump {
    gap: 0.2rem;
  }

  .toggle {
    gap: 0.35rem;
    font-size: 0.85rem;
    color: var(--ink);
    cursor: pointer;
  }
</style>
