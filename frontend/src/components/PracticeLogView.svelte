<script lang="ts">
  /**
   * The practice log: what you actually played, versus what you meant to.
   *
   * Everything here is measured from MIDI rather than claimed, which is the whole
   * reason the logger exists as a passive layer. The one thing it cannot see is
   * the intention, and that is what a workout supplies.
   */
  import { untrack } from 'svelte';
  import { api } from '../lib/api';
  import { app } from '../lib/state.svelte';
  import {
    type AnalyticsSummary,
    type IdentificationQuality,
    type RatingHistory,
    type SystemStatus,
    type PieceSummary,
    type SittingDetail,
    type SittingSummary,
  } from '../lib/types';
  import BackupPanel from './BackupPanel.svelte';
  import CaptureBar from './CaptureBar.svelte';
  import IdentificationQualityCard from './IdentificationQualityCard.svelte';
  import PracticeLogSummary from './PracticeLogSummary.svelte';
  import SegmentTimeline from './SegmentTimeline.svelte';
  import SittingList from './SittingList.svelte';
  import SystemHealthCard from './SystemHealthCard.svelte';
  import WeekReviewCard from './WeekReviewCard.svelte';
  import { formatClock } from '../lib/clock';
  import { inverseOf, type UndoAction } from '../lib/segmentUndo';
  import { createPollRunner, detailIsStale } from '../lib/pollGate';

  let summary = $state<AnalyticsSummary | null>(null);
  let week = $state<RatingHistory | null>(null);
  let system = $state<SystemStatus | null>(null);
  //: Long enough not to be noise, short enough that a finished sitting appears
  //: while the player is still looking at the screen.
  const POLL_MS = 20_000;
  //: A sitting the server is still preparing is asked about every this often, a bounded
  //: number of times: the work is under a second on a real sitting, and the poll above is
  //: the backstop if it never finishes.
  const PREPARING_RETRY_MS = 700;
  const PREPARING_TRIES = 10;
  let quality = $state<IdentificationQuality | null>(null);
  let matching = $state(false);
  let matchNote = $state<string | null>(null);
  let sittings = $state<SittingSummary[]>([]);
  let detail = $state<SittingDetail | null>(null);
  let pieces = $state<PieceSummary[]>([]);
  let days = $state(30);
  let selectedId = $state<number | null>(null);
  let busy = $state(false);
  /**
   * What the last edit could be taken back with.
   *
   * Deliberately **not** persisted: it describes one action in this page's history, and a
   * remembered undo across a reload would silently apply to a different list of segments
   * (20-D3). Reloading the page is how you lose the offer, and the card says so.
   */
  let undo = $state<{ action: UndoAction } | null>(null);
  let error = $state<string | null>(null);
  let importing = $state(false);
  let importNote = $state<string | null>(null);

  async function lookForMatches(): Promise<void> {
    matching = true;
    matchNote = null;
    error = null;
    try {
      const report = await api.practice.autotag();
      matchNote =
        report.considered === 0
          ? 'Every segment already has a piece.'
          : `${report.assigned} of ${report.considered} segments were matched confidently; ` +
            `${report.offered} are waiting for you in the timeline.`;
      await load();
    } catch (cause) {
      error = cause instanceof Error ? cause.message : String(cause);
    } finally {
      matching = false;
    }
  }

  /**
   * What an edit can change: the totals and the sitting list.
   *
   * Cheap, and the half of `load` that a label or a boundary genuinely invalidates: a measured
   * 96 ms and 56 ms on the real library, and they go together.
   */
  async function refreshTotals(): Promise<void> {
    const [nextSummary, nextSittings] = await Promise.all([
      api.practice.summary(days),
      api.practice.sittings(50),
    ]);
    summary = nextSummary;
    sittings = nextSittings;
  }

  /**
   * The whole dashboard: once when the tab opens, and from Refresh.
   *
   * The three panels below are reads about the *library* and the *machine*, and they are the
   * expensive ones — the matcher's leave-one-out accuracy measured **866 ms** against the real
   * library, against 96 ms for the totals. They used to be refetched after every label, split
   * and merge, which is where a one-second stall per click came from.
   *
   * `allSettled`, and together rather than in series: none of the three may take the log down,
   * and awaiting them one after another costs the sum of their times instead of the longest.
   */
  async function load(): Promise<void> {
    error = null;
    try {
      await refreshTotals();
      const [nextWeek, nextSystem, nextQuality] = await Promise.allSettled([
        api.progressRatings(7),
        api.systemStatus(),
        api.practice.identificationQuality(),
      ]);
      week = nextWeek.status === 'fulfilled' ? nextWeek.value : null;
      system = nextSystem.status === 'fulfilled' ? nextSystem.value : null;
      quality = nextQuality.status === 'fulfilled' ? nextQuality.value : null;
      await openSelectedSitting();
    } catch (cause) {
      error = cause instanceof Error ? cause.message : String(cause);
    }
  }

  /**
   * Keep the timeline pointed at the same sitting across a refresh.
   *
   * The sitting is always re-read rather than patched from the list: `load` runs after a
   * re-segment too, and a timeline drawn from a stale detail looked like it had ignored the
   * edit — which is worse than a stale number.
   */
  async function openSelectedSitting(): Promise<void> {
    if (selectedId !== null && sittings.some((row) => row.id === selectedId)) {
      await select(selectedId);
    } else if (sittings.length > 0 && selectedId === null) {
      await select(sittings[0].id);
    } else if (selectedId !== null) {
      selectedId = null;
      detail = null;
    }
  }

  async function select(id: number): Promise<void> {
    selectedId = id;
    app.reflect({ name: 'log', entity: { kind: 'sitting', id } });
    try {
      detail = await api.practice.sitting(id);
      if (detail.preparing) void awaitPreparation(id);
    } catch (cause) {
      error = cause instanceof Error ? cause.message : String(cause);
    }
  }

  /**
   * Watch a sitting the server is still preparing.
   *
   * A scheduled sitting answers immediately with `preparing` rather than making the click wait
   * for the segmentation, so opening the log a second after switching the piano off shows a
   * short "preparing" and then the timeline. The retry is bounded on purpose: if the work never
   * finishes — the job failed, or the process restarted mid-sitting — the twenty-second poll is
   * the backstop, and this must not become a component that fetches for ever.
   */
  async function awaitPreparation(id: number): Promise<void> {
    for (let attempt = 0; attempt < PREPARING_TRIES; attempt += 1) {
      await new Promise((resolve) => setTimeout(resolve, PREPARING_RETRY_MS));
      // The player may have selected something else, or started an edit whose own re-read
      // owns `detail`; either way this loop has lost the right to write it.
      if (selectedId !== id || busy) return;
      try {
        const next = await api.practice.sitting(id);
        if (selectedId !== id) return;
        detail = next;
        if (!next.preparing) return;
      } catch {
        // A failed retry is not worth a banner: the poll still runs, and the read that
        // materialises the sitting itself is only ever one request away.
        return;
      }
    }
  }

  /**
   * Every edit applies the server's own answer, then refreshes only the totals.
   *
   * The response *is* what the timeline draws: `assignSegment`, `setSegmentKind`, `splitSegment`,
   * `mergeSegments`, `resegment` and `identify` all answer with the sitting's segments, and this
   * used to throw that away and re-read the same rows — along with three panels an edit cannot
   * have changed.
   *
   * `SittingDetail` carries more than its segments, but nothing an edit moves lives outside
   * them: a split changes boundaries, not the sitting's duration or its note count.
   *
   * It is also the single funnel every timeline edit goes through, which is what makes it the
   * right place to work out whether the edit can be taken back — the segments before and after
   * are both in hand here and nowhere else.
   */
  async function edit(
    action: () => Promise<unknown>,
    options: { undoable?: boolean } = {},
  ): Promise<void> {
    busy = true;
    error = null;
    const before = detail?.segments ?? [];
    try {
      const result = await action();
      if (detail !== null && Array.isArray(result)) {
        // Re-read rather than patch the segments in place. The response does carry the
        // segments, but since Phase 22c a sitting's detail also carries its *passages*, which
        // are derived from the attempts: patching the segments alone would leave the passage
        // layer describing the state before the edit, so the view would be showing a grouping
        // of attempts that no longer exist. One read, and the timeline is one consistent thing.
        detail = await api.practice.sitting(detail.id);
      }
      await refreshTotals();
      // Derived by diffing the rows rather than by remembering which button was pressed, so the
      // offer cannot disagree with what actually happened. `undoable: false` is for the undo
      // itself, so pressing it twice cannot ping-pong between two states for ever.
      const next =
        options.undoable === false || detail === null ? null : inverseOf(before, detail.segments);
      undo = next === null ? null : { action: next };
    } catch (cause) {
      error = cause instanceof Error ? cause.message : String(cause);
      undo = null;
    } finally {
      busy = false;
    }
  }

  function applyUndo(action: UndoAction): Promise<unknown> {
    if (action.kind === 'assign') {
      return api.practice.assignSegment(action.segmentId, action.pieceId);
    }
    if (action.kind === 'merge') {
      return api.practice.mergeSegments(action.segmentId, action.otherId);
    }
    return api.practice.splitSegment(action.segmentId, action.atMs);
  }

  async function undoLast(): Promise<void> {
    if (undo === null) return;
    const action = undo.action;
    await edit(() => applyUndo(action), { undoable: false });
  }

  /**
   * Label a whole passage at once.
   *
   * The label lives on the segments (22-D2), so this is the route that already exists, sent
   * once per member rather than a new one: nothing about where a label is stored changes, and
   * there is no group to keep in step with the segments. `undoable` is off because the inverse
   * of a many-segment write is not one action, and offering one would be a lie.
   */
  async function labelPassage(attemptIds: number[], pieceId: number | null): Promise<void> {
    await edit(
      async () => {
        let last: unknown = [];
        for (const id of attemptIds) last = await api.practice.assignSegment(id, pieceId);
        return last;
      },
      { undoable: false },
    );
  }

  async function importHistory(): Promise<void> {
    importing = true;
    importNote = null;
    try {
      const report = await api.practice.importLegacy();
      importNote = report.available
        ? `${report.sittings} sittings, ${report.note_events} notes and ${report.segments} segments imported.`
        : (report.note ?? 'Nothing to import.');
      await load();
    } catch (cause) {
      importNote = cause instanceof Error ? cause.message : String(cause);
    } finally {
      importing = false;
    }
  }

  // Open the sitting a link asked for, once. `consumeEntity` clears the request.
  $effect(() => {
    const id = app.consumeEntity('sitting');
    if (id !== null && id !== selectedId) void select(id);
  });

  $effect(() => {
    // Re-read when the window changes or a performance is scored, so the log
    // does not go stale behind a workout the player just finished. `untrack`
    // keeps the fetch's own bookkeeping (which sitting is selected) out of the
    // dependency set, so selecting a sitting cannot re-trigger the fetch.
    days;
    app.revision;
    untrack(() => {
      void load();
    });
  });

  /**
   * Keep the dashboard current while it is on screen.
   *
   * A sitting is materialised — and so appears here — only once it has been quiet
   * for the sitting gap, or as soon as the piano goes away and the client says so.
   * Neither is an event this view otherwise hears about, so without a poll the
   * newest sitting is invisible until the page is reloaded, which is exactly what
   * it was doing.
   *
   * `keepSelection` on purpose: a poll must never move the player's attention. It
   * refreshes the tiles, the list and the open sitting's detail, and leaves the
   * selection exactly as it was — including none at all.
   *
   * Every entry point goes through `poll` rather than `refreshQuietly` directly, because two
   * entry points exist (the interval and coming back to the tab) and they can fire a second
   * apart. Ungated, a read slower than the interval stacked: the owner's notebook was measured
   * at 70 s for one large sitting's detail right after a restart, and the twenty-second polls
   * queued behind each other until the log took minutes to open. See `lib/pollGate.ts`.
   */
  const poll = createPollRunner(refreshQuietly);

  $effect(() => {
    // A hidden tab asks for nothing. The poll exists so the person *looking at the screen* sees
    // the newest sitting without pressing F5, and a tab behind another window was paying the
    // same server cost for nobody: 110 ms of SQLite per poll on the owner's library, on the slow
    // laptop that is also capturing the piano.
    const tick = () => {
      if (document.visibilityState === 'hidden') return;
      void poll.fire();
    };
    const timer = setInterval(tick, POLL_MS);
    // And catch up the moment it is looked at again, so coming back to the tab is instant rather
    // than up to a full interval stale.
    const onVisible = () => {
      if (document.visibilityState === 'visible') void poll.fire();
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      clearInterval(timer);
      document.removeEventListener('visibilitychange', onVisible);
    };
  });

  /** The poll: same reads as `load`, minus anything that touches the selection. */
  async function refreshQuietly(): Promise<void> {
    // Never while an edit is in flight: that path re-reads everything itself, and
    // two overlapping reads could land out of order.
    if (busy) return;
    try {
      const [nextSummary, nextSittings] = await Promise.all([
        api.practice.summary(days),
        api.practice.sittings(50),
      ]);
      summary = nextSummary;
      sittings = nextSittings;
      const row =
        selectedId === null ? undefined : nextSittings.find((it) => it.id === selectedId);
      // Only when the sitting actually changed. The detail is the expensive read — on the
      // owner's library it is 30 000 notes' worth of derived work, and after a restart it was
      // measured at 70 s — and the list row above already says whether anything moved.
      if (row !== undefined && detailIsStale(row, detail)) {
        detail = await api.practice.sitting(row.id);
      }
    } catch {
      // A missed poll is not worth an error banner: the next one is in a few
      // seconds, and every explicit action still reports its own failures.
    }
  }

  $effect(() => {
    void api.repertoire
      .pieces()
      .then((rows) => (pieces = rows))
      .catch(() => {
        // The assign dropdown is a convenience; the log works without it.
      });
  });
</script>

<section class="card head">
  <div class="spread wrap">
    <div>
      <h2>Practice log</h2>
      <p class="muted small">
        Recorded from your playing, not typed in afterwards. A sitting opens on the
        first note and closes after five minutes of silence.
      </p>
    </div>
    <div class="row wrap">
      <label class="row window">
        <span class="muted small">Window</span>
        <select bind:value={days}>
          <option value={7}>7 days</option>
          <option value={30}>30 days</option>
          <option value={90}>90 days</option>
          <option value={365}>1 year</option>
        </select>
      </label>
      <label class="row window">
        <span class="muted small">Target</span>
        <select
          value={app.weeklyTargetDays}
          onchange={(event) =>
            app.setWeeklyTargetDays(Number((event.currentTarget as HTMLSelectElement).value))}
        >
          {#each [1, 2, 3, 4, 5, 6, 7] as target (target)}
            <option value={target}>{target} days/week</option>
          {/each}
        </select>
      </label>
      <button class="ghost" disabled={busy} onclick={() => void load()}>Refresh</button>
      <button class="ghost" disabled={importing} onclick={() => void importHistory()}>
        {importing ? 'Importing…' : 'Import old history'}
      </button>
    </div>
  </div>
  {#if importNote}
    <p class="muted small">{importNote}</p>
  {/if}
</section>

<CaptureBar />

{#if error}
  <div class="error-banner">{error}</div>
{/if}

{#if summary}
  <PracticeLogSummary {summary} />
{/if}

<div class="columns wide-left">
  <section class="card">
    <h3>Recent sittings</h3>
    <SittingList {sittings} {selectedId} onselect={(id) => void select(id)} />
  </section>

  {#if detail}
    <!--
      The notice and the card are one grid column between them. `.columns` is a grid, and a grid
      child is a *column*, not a banner: as a sibling, the notice took the second column for
      itself and pushed the timeline into the sitting list's cell, so the detail rendered under
      the list in the narrow column while the wide one held nothing but the notice. The wrapper
      is what keeps the pair in the column they are laid out for.
    -->
    <div class="stack">
      {#if undo}
        <div class="row wrap" data-undo>
          <span class="muted small">
            Changed the timeline. This offer lasts until the page is reloaded.
          </span>
          <button class="ghost tiny" disabled={busy} onclick={() => void undoLast()}>
            {undo.action.label}
          </button>
        </div>
      {/if}
      {#if detail.preparing}
        <!--
          The server is segmenting this sitting, measuring it and looking for the pieces. It
          answers immediately instead of making the click wait, so say what is happening
          rather than drawing an empty timeline that looks like a sitting with nothing in it.
        -->
        <section class="card empty" data-preparing>
          <p class="muted small">
            Preparing this sitting — finding the passages and the pieces you played. It will
            appear here in a moment.
          </p>
        </section>
      {:else}
        <SegmentTimeline
          {detail}
          {pieces}
          {busy}
          onassign={(segmentId, pieceId) =>
            void edit(() => api.practice.assignSegment(segmentId, pieceId))}
          onkinds={(segmentId, body) =>
            void edit(() => api.practice.setSegmentKind(segmentId, body))}
          onsplit={(segmentId, atMs) => void edit(() => api.practice.splitSegment(segmentId, atMs))}
          onmerge={(segmentId, otherId) =>
            void edit(() => api.practice.mergeSegments(segmentId, otherId))}
          onlabelpassage={(attemptIds, pieceId) => void labelPassage(attemptIds, pieceId)}
          onresegment={async (confirm) => {
            await edit(() => api.practice.resegment(detail!.id, confirm));
            // Re-segmenting rebuilds the rows the matcher was measured against, so its panel is
            // the one thing here that a refresh can legitimately move.
            quality = await api.practice.identificationQuality().catch(() => quality);
          }}
          onidentify={(segmentId, action) =>
            // Answering the matcher has no inverse. The label does come back, but the
            // `identification_outcomes` row recording the guess does not — a merge nulls it and nothing
            // writes it again — so offering "Undo label" here would leave the accuracy figure claiming
            // a decision that had been taken back. `inverseOf` cannot tell this apart from an ordinary
            // assignment, because the segments look identical either way, so the suppression lives at
            // the call site that knows which route it is.
            void edit(() => api.practice.identify(segmentId, action), { undoable: false })}
        />
      {/if}
    </div>
  {:else}
    <section class="card empty">
      <p class="muted small">Select a sitting to see what it contained.</p>
    </section>
  {/if}
</div>

{#if summary}
  <WeekReviewCard {summary} {week} weeklyTargetDays={app.weeklyTargetDays} />
{/if}

{#if system}
  <SystemHealthCard {system} />
{/if}

{#if quality}
  <IdentificationQualityCard
    {quality}
    {matching}
    {matchNote}
    onLookForMatches={() => void lookForMatches()}
  />
{/if}

<BackupPanel onrestored={() => void load()} />

<section class="card totals">
  <h3>Totals</h3>
  <ul class="muted small">
    <li>
      Longest sitting:
      {sittings.length
        ? formatClock(Math.max(...sittings.map((row) => row.duration_s)))
        : '—'}
    </li>
    <li>Sittings recorded: {sittings.length}</li>
  </ul>
</section>

<style>
  .head,
  .totals {
    padding: 0.75rem 0.9rem;
    display: flex;
    flex-direction: column;
    gap: 0.45rem;
  }

  /* `align-items: start` is load-bearing, not tidiness. A grid item stretches to the row height
     by default, and the two columns have very different heights: the sitting list is capped at
     22rem while the detail (transport, strip, segment list, roll) is far taller. Stretching drew
     the sittings card as a box hundreds of pixels taller than its list — a large bordered void
     under the last sitting, which reads as missing content. Each card now takes its own height. */
  .columns {
    display: grid;
    align-items: start;
    grid-template-columns: repeat(auto-fit, minmax(20rem, 1fr));
    gap: 0.75rem;
  }

  .columns.wide-left {
    grid-template-columns: minmax(18rem, 1fr) minmax(22rem, 1.4fr);
  }

  @media (max-width: 900px) {
    .columns.wide-left {
      grid-template-columns: 1fr;
    }
  }

  section.card:not(.head):not(.totals):not(.empty) {
    padding: 0.75rem 0.9rem;
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
  }

  .empty {
    padding: 0.9rem;
  }

  .small {
    font-size: 0.8rem;
  }

  .window {
    gap: 0.35rem;
  }
</style>
