<script lang="ts">
  import type { ExpectedNote, NoteStatus } from '../lib/types';
  import { midiToName } from '../lib/types';

  interface Props {
    notes: ExpectedNote[];
    statuses: Map<number, NoteStatus>;
  }

  let { notes, statuses }: Props = $props();

  const rows = $derived(
    notes.map((note) => ({
      note,
      status: statuses.get(note.index) ?? ('pending' as NoteStatus),
    })),
  );

  const tally = $derived.by(() => {
    const counts: Record<string, number> = { correct: 0, wrong_pitch: 0, missed: 0, pending: 0, extra: 0 };
    for (const row of rows) counts[row.status] = (counts[row.status] ?? 0) + 1;
    return counts;
  });
</script>

<div class="strip">
  <div class="head">
    <h3>Notes</h3>
    <div class="row wrap legend">
      <span class="tag correct">{tally.correct} right</span>
      <span class="tag wrong">{tally.wrong_pitch} wrong</span>
      <span class="tag missed">{tally.missed} missed</span>
      <span class="muted small">{tally.pending} to go</span>
    </div>
  </div>

  <ol class="notes">
    {#each rows as row (row.note.index)}
      <li class="note {row.status}" title="bar {row.note.measure}, beat {row.note.beat.toFixed(2)}">
        <span class="name mono">{midiToName(row.note.pitch)}</span>
        <span class="hand">{row.note.hand}</span>
      </li>
    {/each}
  </ol>
</div>

<style>
  .strip {
    border: 1px solid var(--line);
    border-radius: var(--radius);
    background: var(--surface-2);
    padding: 0.55rem 0.65rem;
    display: flex;
    flex-direction: column;
    gap: 0.45rem;
  }

  .head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.6rem;
    flex-wrap: wrap;
  }

  .legend {
    gap: 0.35rem;
  }

  .notes {
    display: flex;
    flex-wrap: wrap;
    gap: 0.28rem;
    list-style: none;
    margin: 0;
    padding: 0;
    max-height: 8.5rem;
    overflow-y: auto;
  }

  .note {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.05rem;
    min-width: 2.4rem;
    padding: 0.2rem 0.3rem;
    border-radius: 7px;
    border: 1px solid var(--line);
    background: var(--surface);
    font-size: 0.72rem;
    transition: background 0.1s ease, border-color 0.1s ease, color 0.1s ease;
  }

  .name {
    font-weight: 600;
  }

  .hand {
    font-size: 0.6rem;
    color: var(--muted);
    letter-spacing: 0.04em;
  }

  .note.correct {
    background: var(--good-soft);
    border-color: #b9dfc6;
    color: var(--good);
  }

  .note.wrong_pitch {
    background: var(--bad-soft);
    border-color: #efc4c4;
    color: var(--bad);
  }

  .note.missed {
    background: var(--warn-soft);
    border-color: #eed6b4;
    color: var(--warn);
  }

  .small {
    font-size: 0.75rem;
  }

  .tag {
    font-size: 0.75rem;
    padding: 0.1rem 0.45rem;
    border-radius: 999px;
  }

  .tag.correct {
    background: var(--good-soft);
    color: var(--good);
  }

  .tag.wrong {
    background: var(--bad-soft);
    color: var(--bad);
  }

  .tag.missed {
    background: var(--warn-soft);
    color: var(--warn);
  }
</style>
