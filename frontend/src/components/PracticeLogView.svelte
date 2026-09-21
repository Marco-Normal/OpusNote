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
    formatMinutes,
    formatSize,
    type AnalyticsSummary,
    type IdentificationQuality,
    type RatingHistory,
    type SystemStatus,
    type PieceSummary,
    type SittingDetail,
    type SittingSummary,
  } from '../lib/types';
  import BackupPanel from './BackupPanel.svelte';
  import BarChart from './BarChart.svelte';
  import CalendarHeatmap from './CalendarHeatmap.svelte';
  import CaptureBar from './CaptureBar.svelte';
  import SegmentTimeline from './SegmentTimeline.svelte';
  import SittingList from './SittingList.svelte';
  import { formatClock } from '../lib/clock';
  import { practiceKindLabel } from '../lib/kinds';
  import { inverseOf, type UndoAction } from '../lib/segmentUndo';

  let summary = $state<AnalyticsSummary | null>(null);
  let week = $state<RatingHistory | null>(null);
  let system = $state<SystemStatus | null>(null);
  //: Long enough not to be noise, short enough that a finished sitting appears
  //: while the player is still looking at the screen.
  const POLL_MS = 20_000;
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

  /** "localhost:8000" when a client has checked in, "not reporting" when none has. */
  function captureHeadline(data: AnalyticsSummary): string {
    if (!data.capture) return 'not reporting';
    return data.capture.enabled ? data.capture.origin : 'paused';
  }

  function backupAge(seconds: number): string {
    const hours = seconds / 3600;
    if (hours < 1) return `${Math.round(seconds / 60)} min ago`;
    if (hours < 48) return `${Math.round(hours)} h ago`;
    return `${Math.round(hours / 24)} days ago`;
  }

  /** A rate with its counts, and an em dash when there is nothing to divide. */
  function rate(label: string, value: number | null, correct: number, attempts: number): string {
    return value === null ? `${label} —` : `${label} ${Math.round(value * 100)}% (${correct}/${attempts})`;
  }

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

  function lastNoteLabel(data: AnalyticsSummary): string {
    if (data.last_note_ms === null) return 'no notes recorded yet';
    const seconds = Math.max(0, Math.round((Date.now() - data.last_note_ms) / 1000));
    if (seconds < 90) return `last note ${seconds} s ago`;
    return `last note ${Math.round(seconds / 60)} min ago`;
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
    } catch (cause) {
      error = cause instanceof Error ? cause.message : String(cause);
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
        detail = { ...detail, segments: result as SittingDetail['segments'] };
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
   */
  $effect(() => {
    const timer = setInterval(() => {
      void refreshQuietly();
    }, POLL_MS);
    return () => clearInterval(timer);
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
      if (selectedId !== null && nextSittings.some((row) => row.id === selectedId)) {
        detail = await api.practice.sitting(selectedId);
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
  <section class="card stats">
    <div class="stat">
      <span class="muted small">Logged practice</span>
      <strong>{formatMinutes(summary.total_minutes)}</strong>
      <span class="muted small">{summary.total_notes} notes all time</span>
    </div>
    <div class="stat">
      <span class="muted small">Today</span>
      <strong>{formatMinutes(summary.today_minutes)}</strong>
      <span class="muted small">{summary.calendar.at(-1)?.notes ?? 0} notes</span>
    </div>
    <div class="stat" data-streak={summary.streak_days}>
      <span class="muted small">Streak</span>
      <strong>{summary.streak_days} {summary.streak_days === 1 ? 'day' : 'days'}</strong>
      <span class="muted small">
        {summary.streak_grace_used > 0
          ? 'counting 1 rest day'
          : 'consecutive days played'}
      </span>
    </div>
    <div class="stat">
      <span class="muted small">Workouts</span>
      <strong>{summary.workouts_this_week} this week</strong>
      <span class="muted small">{summary.workouts_completed} completed all time</span>
    </div>
    <div class="stat" data-capture-stat={summary.capture ? 'reporting' : 'silent'}>
      <span class="muted small">Capture</span>
      <strong>{captureHeadline(summary)}</strong>
      <span class="muted small">{lastNoteLabel(summary)}</span>
    </div>
  </section>

  <section class="card">
    <h3>Practice calendar</h3>
    <CalendarHeatmap days={summary.calendar} />
  </section>

  <div class="columns">
    <section class="card">
      <h3>Time per piece</h3>
      {#if summary.by_piece.length === 0}
        <p class="muted small">
          Nothing attributed yet. Tag a segment below and its time lands here.
        </p>
      {:else}
        <BarChart
          items={summary.by_piece.slice(0, 8).map((piece) => ({
            label: piece.title,
            sublabel: piece.composer_name ?? undefined,
            value: piece.minutes,
            hint: `${piece.segments} segment${piece.segments === 1 ? '' : 's'} · last played ${piece.last_played ?? '—'}`,
          }))}
        />
      {/if}
    </section>

    <section class="card">
      <h3>Neglected</h3>
      {#if summary.neglected.length === 0}
        <p class="muted small">No active pieces in the library yet.</p>
      {:else}
        <ul class="neglected">
          {#each summary.neglected as piece (piece.piece_id)}
            <li>
              <span>
                {piece.title}
                {#if piece.composer_name}
                  <span class="muted small">· {piece.composer_name}</span>
                {/if}
              </span>
              <span class="pill" class:warn={(piece.days_since ?? 999) > 14}>
                {piece.days_since === null ? 'never logged' : `${piece.days_since} d ago`}
              </span>
            </li>
          {/each}
        </ul>
      {/if}
    </section>
  </div>

  {#if summary.sources.length > 0}
    <section class="card">
      <h3>How the time was spent</h3>
      <div class="row wrap">
        {#each summary.sources as source (source.source)}
          <span class="pill" class:accent={source.source === 'sight_reading'}>
            {source.source === 'sight_reading' ? 'sight-reading' : 'piano'} ·
            {formatMinutes(source.minutes)} · {source.notes} notes
          </span>
        {/each}
      </div>
      {#if summary.kinds.length > 0}
        <div class="row wrap" data-kind-split>
          {#each summary.kinds as entry (entry.kind ?? 'untagged')}
            <span class="pill" class:accent={entry.kind === 'slow'}>
              {practiceKindLabel(entry.kind)} · {formatMinutes(entry.minutes)} ·
              {entry.segments}
              {entry.segments === 1 ? 'segment' : 'segments'}
            </span>
          {/each}
        </div>
      {/if}
    </section>
  {/if}
{/if}

<div class="columns wide-left">
  <section class="card">
    <h3>Recent sittings</h3>
    <SittingList {sittings} {selectedId} onselect={(id) => void select(id)} />
  </section>

  {#if detail}
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
  {:else}
    <section class="card empty">
      <p class="muted small">Select a sitting to see what it contained.</p>
    </section>
  {/if}
</div>

{#if summary}
  <section class="card review" data-week-review>
    <h3>This week</h3>
    <div class="review-grid">
      <div>
        <span class="muted small">Practised</span>
        <strong>{formatMinutes(summary.calendar.slice(-7).reduce((sum, day) => sum + day.minutes, 0))}</strong>
        <span class="muted small">
          over {summary.calendar.slice(-7).filter((day) => day.minutes > 0).length} days
        </span>
      </div>
      <div>
        <span class="muted small">Sight-reading</span>
        <strong>{summary.workouts_this_week} workouts</strong>
        <span class="muted small">
          {summary.streak_days}-day streak{summary.streak_grace_used > 0 ? ' · 1 rest day' : ''}
        </span>
      </div>
      <div>
        <span class="muted small">Most improved</span>
        {#if week && week.biggest_gain}
          <strong>{week.biggest_gain}</strong>
          <span class="muted small">
            {week.biggest_gain_delta > 0 ? '+' : ''}{week.biggest_gain_delta} rating
          </span>
        {:else}
          <strong class="muted">—</strong>
          <span class="muted small">nothing scored yet</span>
        {/if}
      </div>
      <div>
        <span class="muted small">Neglected</span>
        {#if summary.neglected.length > 0}
          <strong>{summary.neglected[0].title}</strong>
          <span class="muted small">
            {summary.neglected[0].days_since === null
              ? 'never logged'
              : `${summary.neglected[0].days_since} days`}
          </span>
        {:else}
          <strong class="muted">—</strong>
          <span class="muted small">no active pieces</span>
        {/if}
      </div>
    </div>
    <BarChart
      items={summary.calendar.slice(-7).map((day) => ({
        label: day.date.slice(5),
        value: day.minutes,
      }))}
      unit=" min"
    />
  </section>
{/if}

{#if system}
  <section class="card health" data-system-status>
    <h3>System</h3>
    <div class="health-grid">
      <div>
        <span class="muted small">Database</span>
        <strong>{(system.database_bytes / 1024 / 1024).toFixed(1)} MB</strong>
        <span class="muted small">
          {system.wal_bytes > 0
            ? `plus ${(system.wal_bytes / 1024).toFixed(0)} KB of WAL`
            : 'checkpointed'}
        </span>
      </div>
      <div>
        <span class="muted small">Recordings</span>
        <strong>{system.media.present} present</strong>
        <span class="muted small">
          {system.media.pending} to copy{#if system.media.missing}, {system.media.missing} missing{/if}
        </span>
      </div>
      <div>
        <span class="muted small">Recorded here</span>
        <strong>{formatSize(system.captured_audio_bytes)}</strong>
        <span class="muted small">takes this app captured — delete them in Repertoire</span>
      </div>
      <div>
        <span class="muted small">Backups</span>
        <strong>{system.backup_count} kept</strong>
        <span class="muted small">
          {#if system.last_backup_seconds === null}
            none yet
          {:else}
            newest {backupAge(system.last_backup_seconds)}
          {/if}
        </span>
      </div>
      <div>
        <span class="muted small">Piano visible to ALSA</span>
        <strong>{system.alsa_clients.some((name) => /casio|piano/i.test(name)) ? 'yes' : 'no'}</strong>
        <span class="muted small">
          {#if !system.sequencer}
            sequencer not loaded
          {:else}
            {system.alsa_clients.filter((name) => !/midi through|system/i.test(name)).join(', ') ||
              'only virtual ports'}
          {/if}
        </span>
      </div>
    </div>
    {#if system.last_backup_seconds === null && system.backup_count === 0}
      <p class="muted small">
        No nightly backup has run yet. The installer enables a timer that writes one at
        03:10 and keeps the last 14.
      </p>
    {/if}
  </section>
{/if}

{#if quality}
  <section class="card identify" data-identification>
    <div class="row wrap spread">
      <h3>Recognising what you played</h3>
      <button class="ghost tiny" disabled={matching} onclick={() => void lookForMatches()}>
        {matching ? 'Looking…' : 'Look for matches'}
      </button>
    </div>

    {#if quality.evaluated === 0}
      <p class="muted small">
        Nothing to measure yet. The matcher learns from the segments you have tagged
        by hand: {quality.labelled}
        {quality.labelled === 1 ? 'segment is' : 'segments are'} labelled, and
        {quality.labelled < 2
          ? 'two are the minimum, because the first one has nothing to be compared against.'
          : 'a measurement needs at least two.'}
      </p>
    {:else}
      <div class="health-grid">
        <div>
          <span class="muted small">Right first time</span>
          <strong>{quality.accuracy === null ? '—' : `${Math.round(quality.accuracy * 100)}%`}</strong>
          <span class="muted small">
            {quality.correct_top}/{quality.evaluated} labels, each hidden and guessed back
          </span>
        </div>
        <div>
          <span class="muted small">In the top three</span>
          <strong>{quality.top3_accuracy === null ? '—' : `${Math.round(quality.top3_accuracy * 100)}%`}</strong>
          <span class="muted small">{quality.correct_top3}/{quality.evaluated}</span>
        </div>
        <div>
          <span class="muted small">Written without asking</span>
          <strong>{rate('', quality.auto_precision, quality.auto_correct, quality.auto_attempted).trim() || '—'}</strong>
          <span class="muted small">
            {quality.auto_attempted} of {quality.evaluated} segments
            ({quality.auto_coverage === null ? '—' : `${Math.round(quality.auto_coverage * 100)}%`})
          </span>
        </div>
        <div>
          <span class="muted small">Offered and right</span>
          <strong>{rate('', quality.offered_precision, quality.offered_correct, quality.offered_attempted).trim() || '—'}</strong>
          <span class="muted small">
            {quality.offered_attempted} offered, {quality.unresolved} it could not judge
          </span>
        </div>
      </div>

      <p class="muted small">
        Measured by hiding each of your {quality.labelled} hand-tagged segments in turn and
        seeing whether the matcher names the right piece without it. On your own library,
        including the pieces that sound like each other.
        {#if quality.skipped}
          {quality.skipped} older labels were left out to keep this quick.
        {/if}
      </p>
    {/if}

    {#if quality.inferred > 0}
      <p class="muted small" data-inferred-count>
        {quality.inferred}
        {quality.inferred === 1 ? 'segment carries' : 'segments carry'} a label the matcher
        wrote. {#if quality.settled > 0}
          Of the {quality.settled} you have since judged,
          {quality.confirmed} were right, {quality.changed} you corrected and
          {quality.rejected} you threw out
          {#if quality.live_precision !== null}
            — {Math.round(quality.live_precision * 100)}% left alone.
          {/if}
        {:else}
          None judged yet: each one is marked <em>guessed</em> in the timeline until you
          accept or correct it.
        {/if}
        {#if quality.dismissed > 0}
          You have also declined {quality.dismissed}
          {quality.dismissed === 1 ? 'suggestion' : 'suggestions'}, which is not counted
          against the matcher.
        {/if}
      </p>
    {/if}

    {#each quality.notes as note}
      <p class="muted small">{note}</p>
    {/each}
    {#if matchNote}
      <div class="notice">{matchNote}</div>
    {/if}
  </section>
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

  .identify {
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
  }

  .identify h3 {
    margin: 0;
  }

  .health {
    display: flex;
    flex-direction: column;
    gap: 0.7rem;
    padding: 0.75rem 0.9rem;
  }

  .health-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(9rem, 1fr));
    gap: 0.75rem;
  }

  .health-grid > div {
    display: flex;
    flex-direction: column;
    gap: 0.1rem;
  }

  .health-grid strong {
    font-size: 1.05rem;
  }

  .review {
    display: flex;
    flex-direction: column;
    gap: 0.7rem;
    padding: 0.75rem 0.9rem;
  }

  .review-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(9rem, 1fr));
    gap: 0.75rem;
  }

  .review-grid > div {
    display: flex;
    flex-direction: column;
    gap: 0.1rem;
  }

  .review-grid strong {
    font-size: 1.05rem;
  }

  .stats {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(10rem, 1fr));
    gap: 0.75rem;
    padding: 0.85rem 0.9rem;
  }

  .stat {
    display: flex;
    flex-direction: column;
    gap: 0.1rem;
  }

  .stat strong {
    font-size: 1.25rem;
    letter-spacing: -0.01em;
  }

  .columns {
    display: grid;
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

  section.card:not(.stats):not(.head):not(.totals):not(.empty) {
    padding: 0.75rem 0.9rem;
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
  }

  .empty {
    padding: 0.9rem;
  }

  .neglected {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
    font-size: 0.86rem;
  }

  .neglected li {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
  }

  .small {
    font-size: 0.8rem;
  }

  .window {
    gap: 0.35rem;
  }
</style>
