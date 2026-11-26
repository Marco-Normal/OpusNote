<script lang="ts">
  import { formatClock } from '../lib/clock';
  import { pieceLabel } from '../lib/pieceLabel';
  import type { PieceSummary, PracticePassage } from '../lib/types';

  interface Props {
    passage: PracticePassage;
    tint: string | null;
    displayName: string | null;
    pieces: PieceSummary[];
    pieceNames: Map<number, string>;
    busy: boolean;
    onLabelPassage: (attemptIds: number[], pieceId: number | null) => void;
  }

  let { passage, tint, displayName, pieces, pieceNames, busy, onLabelPassage }: Props = $props();
</script>

<li class="passage" data-passage={passage.attempt_ids[0] ?? passage.start_ms}>
  <div class="head row wrap">
    <span class="pill mono">
      {passage.attempts}
      {passage.attempts === 1 ? 'attempt' : 'attempts'}
    </span>
    <span class="mono range">
      {formatClock(passage.start_ms / 1000)}–{formatClock(passage.end_ms / 1000)}
    </span>
    {#if tint}
      <span class="swatch" style="background: {tint}" aria-hidden="true"></span>
    {/if}
    <strong>{passage.piece_id === null ? 'unidentified' : displayName}</strong>
  </div>
  <!-- Labelling the passage labels every member attempt: the label lives on the
       segments, so this is the route that already exists sent once per member, and
       there is no group to keep in step with them. -->
  <div class="row wrap controls">
    <select
      aria-label="Piece for this passage"
      disabled={busy}
      value={passage.piece_id ?? ''}
      onchange={(event) => {
        const value = (event.currentTarget as HTMLSelectElement).value;
        onLabelPassage(
          passage.attempt_ids,
          value === '' ? null : Number(value),
        );
      }}
    >
      <option value="">— label all {passage.attempts} —</option>
      {#each pieces as piece (piece.id)}
        <option value={piece.id}>{pieceNames.get(piece.id) ?? pieceLabel(piece)}</option>
      {/each}
    </select>
    <span class="muted small">
      one decision for the whole passage — it writes to each attempt below
    </span>
  </div>
</li>

<style>
  /* The row the player thinks in. The attempts it groups are the .segment cards beneath. */
  .passage {
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
    padding: 0.45rem 0.55rem;
    border: 1px solid var(--accent);
    border-radius: 8px;
    background: var(--surface);
  }

  .swatch {
    display: inline-block;
    flex: none;
    width: 0.7rem;
    height: 0.7rem;
    border-radius: 2px;
  }

  .range {
    font-size: 0.84rem;
  }

  .controls {
    gap: 0.45rem;
  }

  select {
    max-width: 16rem;
  }

  .small {
    font-size: 0.78rem;
  }
</style>
