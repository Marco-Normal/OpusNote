<script lang="ts">
  import { api } from '../lib/api';
  import { app } from '../lib/state.svelte';
  import PieceEditor from './PieceEditor.svelte';
  import type {
    Composer,
    ImportReport,
    JournalEntry,
    PieceDetail,
    PieceSummary,
    PracticeSuggestion,
    RepertoireStatus,
    SegmentSummary,
  } from '../lib/types';
  import { formatDuration, formatMinutes, formatSize } from '../lib/types';
  import type { PiecePracticeDetail } from '../lib/types';
  import LineChart from './LineChart.svelte';
  import ScoreViewer from './ScoreViewer.svelte';
  import RecordingPlayer from './RecordingPlayer.svelte';
  import TakeList from './TakeList.svelte';
  import type { Loop } from '../lib/waveform';

  type Grouping = 'none' | 'composer' | 'difficulty';

  let status = $state<RepertoireStatus | null>(null);
  let pieces = $state<PieceSummary[]>([]);
  let composers = $state<Composer[]>([]);
  let suggestions = $state<Map<number, PracticeSuggestion>>(new Map());
  let detail = $state<PieceDetail | null>(null);

  let search = $state('');
  let statusFilter = $state('');
  let composerFilter = $state('');
  let grouping = $state<Grouping>('composer');

  let loading = $state(true);
  let detailLoading = $state(false);
  let error = $state<string | null>(null);
  let importing = $state(false);
  // null = closed, 'new' = creating, a PieceDetail = editing that piece.
  let editing = $state<PieceDetail | 'new' | null>(null);
  let confirmingDelete = $state(false);
  let journalDate = $state(localDate());
  let journalContent = $state('');
  let journalMinutes = $state<number | null>(null);
  let savingJournal = $state(false);
  // Which entry is open for editing, and the draft of it. One at a time: the journal
  // is prose, and two half-edited paragraphs is a way to lose one of them.
  let editingEntry = $state<number | null>(null);
  let editDate = $state('');
  let editMinutes = $state<number | null>(null);
  let editContent = $state('');
  //: Set when the entry is being written about a sitting, from the Log tab.
  let journalSitting = $state<number | null>(null);
  let journalMeasured = $state<string | null>(null);
  //: The newest entries across the library, shown where a piece would be.
  let feedEntries = $state<JournalEntry[]>([]);
  let feedSearch = $state('');
  let feedTimer: ReturnType<typeof setTimeout> | null = null;

  $effect(() => {
    // Read `feedSearch` here so this re-runs when it changes, and pass the value into
    // the debounce so typing a word does not fire a query per keystroke.
    const term = feedSearch;
    if (feedTimer) clearTimeout(feedTimer);
    feedTimer = setTimeout(() => void loadFeed(term), 200);
    return () => {
      if (feedTimer) clearTimeout(feedTimer);
    };
  });

  $effect(() => {
    // Arrived from the Log tab's "Write about this". Consumed and cleared in the same
    // pass, so it opens once and cannot re-fire on a later re-render.
    const draft = app.journalDraft;
    if (!draft) return;
    app.journalDraft = null;
    journalSitting = draft.sittingId;
    journalMeasured = draft.measured;
    void open(draft.pieceId);
  });
  let uploadFile = $state<File | null>(null);
  let fileInput = $state<HTMLInputElement | undefined>(undefined);
  let uploadTitle = $state('');
  let uploading = $state(false);
  let uploadNote = $state<string | null>(null);
  let scoreFile = $state<File | null>(null);
  let scoreInput = $state<HTMLInputElement | undefined>(undefined);
  let scoreTitle = $state('');
  let attachingScore = $state(false);
  let scoreNote = $state<string | null>(null);
  //: Which score is open in the viewer, if any. One at a time: two engravings on
  //: screen at once is a comparison nobody asked this panel for yet.
  let openScoreId = $state<number | null>(null);
  let copyMedia = $state(true);
  let importReport = $state<ImportReport | null>(null);
  //: MIDI-measured practice for the open piece. Fetched separately from the
  //: repertoire payload, because the repertoire domain does not read note events.
  let practice = $state<PiecePracticeDetail | null>(null);
  //: Segments of this piece's sittings, so a take can name the passage it came from.
  let segments = $state<Map<number, SegmentSummary>>(new Map());

  async function load(): Promise<void> {
    loading = true;
    error = null;
    try {
      const [stats, list, composerList, hints] = await Promise.all([
        api.repertoire.status(),
        api.repertoire.pieces(),
        api.repertoire.composers(),
        api.practiceSuggestions(),
      ]);
      status = stats;
      pieces = list;
      composers = composerList;
      suggestions = new Map(hints.map((hint) => [hint.piece_id, hint]));
      if (detail && !list.some((piece) => piece.id === detail?.id)) detail = null;
    } catch (cause) {
      error = cause instanceof Error ? cause.message : String(cause);
    } finally {
      loading = false;
    }
  }

  async function open(pieceId: number): Promise<void> {
    if (detail?.id === pieceId) {
      detail = null;
      return;
    }
    detailLoading = true;
    error = null;
    try {
      detail = await api.repertoire.piece(pieceId);
      practice = await api.practice.piece(pieceId).catch(() => null);
      await loadSegments();
    } catch (cause) {
      error = cause instanceof Error ? cause.message : String(cause);
    } finally {
      detailLoading = false;
    }
  }

  /**
   * The segments the open piece's takes were played in.
   *
   * Only the sittings that actually produced a take: a piece can hold hundreds of segments
   * across years of practice, and fetching them all to label two takes is the wrong trade.
   */
  async function loadSegments(): Promise<void> {
    const sittingIds = [
      ...new Set(
        (detail?.media ?? [])
          .filter((row) => row.source === 'captured' && row.sitting_id !== null)
          .map((row) => row.sitting_id as number),
      ),
    ];
    const found = new Map<number, SegmentSummary>();
    for (const sittingId of sittingIds) {
      const sitting = await api.practice.sitting(sittingId).catch(() => null);
      for (const segment of sitting?.segments ?? []) found.set(segment.id, segment);
    }
    segments = found;
  }

  async function runImport(): Promise<void> {
    importing = true;
    error = null;
    importReport = null;
    try {
      importReport = await api.repertoire.importLegacy(copyMedia);
      // The same legacy database also holds the standalone logger's practice
      // history, so one Import covers both. It is a separate call because it is
      // a separate app's data with its own shape, and either can be re-run alone.
      const practiceReport = await api.practice.importLegacy().catch(() => null);
      if (practiceReport?.available) {
        importReport.notes = [
          ...importReport.notes,
          `Practice history: ${practiceReport.sittings} sittings, ` +
            `${practiceReport.note_events} notes, ${practiceReport.segments} segments.`,
        ];
      }
      await load();
    } catch (cause) {
      error = cause instanceof Error ? cause.message : String(cause);
    } finally {
      importing = false;
    }
  }

  async function afterWrite(pieceId: number | null): Promise<void> {
    await load();
    if (pieceId !== null) {
      detail = await api.repertoire.piece(pieceId);
      practice = await api.practice.piece(pieceId).catch(() => null);
      await loadSegments();
    } else {
      detail = null;
      practice = null;
      segments = new Map();
    }
    editing = null;
    confirmingDelete = false;
    // The cross-piece feed is on screen whenever no piece is selected, so a write
    // from either side has to show up in it.
    void loadFeed(feedSearch);
  }

  async function loadFeed(term: string): Promise<void> {
    try {
      feedEntries = await api.repertoire.journal({ limit: 40, search: term || undefined });
    } catch {
      // The feed is a convenience on an otherwise empty pane. A failure here must not
      // take the whole view over with an error about something the user did not ask
      // for; the pane simply stays empty.
      feedEntries = [];
    }
  }

  /**
   * Today in the player's own timezone.
   *
   * `toISOString().slice(0, 10)` is UTC, so anywhere west of Greenwich it offers
   * yesterday's date through the whole evening — which is when practice happens.
   */
  function localDate(): string {
    const now = new Date();
    const local = new Date(now.getTime() - now.getTimezoneOffset() * 60_000);
    return local.toISOString().slice(0, 10);
  }

  async function addJournalEntry(): Promise<void> {
    if (!detail || !journalContent.trim()) return;
    savingJournal = true;
    error = null;
    try {
      const pieceId = detail.id;
      await api.repertoire.createJournal(pieceId, {
        entry_date: journalDate,
        content: journalContent.trim(),
        practice_minutes: journalMinutes,
        sitting_id: journalSitting,
      });
      journalContent = '';
      journalMinutes = null;
      journalSitting = null;
      journalMeasured = null;
      await afterWrite(pieceId);
    } catch (cause) {
      error = cause instanceof Error ? cause.message : String(cause);
    } finally {
      savingJournal = false;
    }
  }

  function startEditing(entry: JournalEntry): void {
    editingEntry = entry.id;
    editDate = entry.entry_date;
    editMinutes = entry.practice_minutes;
    editContent = entry.content;
    error = null;
  }

  function cancelEditing(): void {
    editingEntry = null;
    editContent = '';
  }

  async function saveEdit(entry: JournalEntry): Promise<void> {
    if (!detail || !editContent.trim()) return;
    savingJournal = true;
    error = null;
    try {
      await api.repertoire.updateJournal(entry.id, {
        entry_date: editDate,
        content: editContent.trim(),
        practice_minutes: editMinutes,
      });
      editingEntry = null;
      await afterWrite(detail.id);
    } catch (cause) {
      error = cause instanceof Error ? cause.message : String(cause);
    } finally {
      savingJournal = false;
    }
  }

  async function removeJournalEntry(entry: JournalEntry): Promise<void> {
    if (!detail) return;
    try {
      await api.repertoire.deleteJournal(entry.id);
      await afterWrite(detail.id);
    } catch (cause) {
      error = cause instanceof Error ? cause.message : String(cause);
    }
  }

  async function importRecording(): Promise<void> {
    if (!detail || !uploadFile) return;
    uploading = true;
    uploadNote = null;
    error = null;
    try {
      const pieceId = detail.id;
      const recorded = await api.repertoire.uploadRecording(pieceId, uploadFile, uploadTitle.trim());
      uploadFile = null;
      uploadTitle = '';
      // Clear the element's value as well as the state. Without this the control
      // goes dead for the file just imported: the browser sees no change when
      // the same file is chosen again, so no `change` event fires and the button
      // stays disabled with no way to retry.
      if (fileInput) fileInput.value = '';
      uploadNote = `Imported “${recorded.original_name ?? recorded.file_name}” as ${recorded.codec}.`;
      await afterWrite(pieceId);
    } catch (cause) {
      // A duplicate is an expected answer, not a failure of the app, so it goes
      // in the notice rather than the error banner.
      const message = cause instanceof Error ? cause.message : String(cause);
      if (message.includes('409')) uploadNote = message.replace(/^.*?: /, '');
      else error = message;
    } finally {
      uploading = false;
    }
  }

  async function removeRecording(recordingId: number): Promise<void> {
    if (!detail) return;
    try {
      await api.repertoire.deleteRecording(recordingId);
      await afterWrite(detail.id);
    } catch (cause) {
      error = cause instanceof Error ? cause.message : String(cause);
    }
  }

  async function attachScore(): Promise<void> {
    if (!detail || !scoreFile) return;
    attachingScore = true;
    scoreNote = null;
    error = null;
    try {
      const pieceId = detail.id;
      const attached = await api.repertoire.uploadScore(
        pieceId,
        scoreFile,
        scoreTitle.trim(),
      );
      scoreFile = null;
      scoreTitle = '';
      // Same reason as the recording input: the browser fires no `change` event
      // when the same file is picked again, so the control would go dead.
      if (scoreInput) scoreInput.value = '';
      scoreNote = `Attached “${attached.original_name ?? attached.file_name}”.`;
      openScoreId = attached.id;
      await afterWrite(pieceId);
    } catch (cause) {
      // "Already attached" is an answer, not a failure, so it belongs in the note.
      const message = cause instanceof Error ? cause.message : String(cause);
      if (message.includes('409')) scoreNote = message.replace(/^.*?: /, '');
      else error = message;
    } finally {
      attachingScore = false;
    }
  }

  async function removeScore(scoreId: number): Promise<void> {
    if (!detail) return;
    try {
      await api.repertoire.deleteRecording(scoreId);
      if (openScoreId === scoreId) openScoreId = null;
      await afterWrite(detail.id);
    } catch (cause) {
      error = cause instanceof Error ? cause.message : String(cause);
    }
  }

  /**
   * Save the A/B loop for one recording.
   *
   * The row's markers are the truth — the player draws whatever comes back — so a
   * refused pair (a loop shorter than the server's minimum, an end past the file)
   * shows up in the error banner with the server's own explanation rather than as
   * a marker that quietly did not stick.
   */
  async function saveLoop(mediaId: number, loop: Loop): Promise<void> {
    if (!detail) return;
    try {
      await api.repertoire.updateRecording(mediaId, {
        loop_start_s: loop.start,
        loop_end_s: loop.end,
      });
      await afterWrite(detail.id);
    } catch (cause) {
      error = cause instanceof Error ? cause.message : String(cause);
    }
  }

  async function removePiece(): Promise<void> {
    if (!detail) return;
    try {
      await api.repertoire.deletePiece(detail.id);
      await afterWrite(null);
    } catch (cause) {
      error = cause instanceof Error ? cause.message : String(cause);
    }
  }

  const visible = $derived(
    pieces.filter((piece) => {
      if (statusFilter && piece.status !== statusFilter) return false;
      if (composerFilter && String(piece.composer_id ?? '') !== composerFilter) return false;
      if (search) {
        const needle = search.trim().toLowerCase();
        const haystack = `${piece.title} ${piece.composer_name ?? ''} ${piece.opus ?? ''}`.toLowerCase();
        if (!haystack.includes(needle)) return false;
      }
      return true;
    }),
  );

  const groups = $derived.by(() => {
    if (grouping === 'none') return [{ label: '', rows: visible }];
    const buckets = new Map<string, PieceSummary[]>();
    for (const piece of visible) {
      const label =
        grouping === 'composer'
          ? (piece.composer_name ?? 'Unknown composer')
          : (piece.difficulty ?? 'Unclassified');
      const bucket = buckets.get(label);
      if (bucket) bucket.push(piece);
      else buckets.set(label, [piece]);
    }
    return [...buckets.entries()]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([label, rows]) => ({ label, rows }));
  });

  const suggestion = $derived(detail ? suggestions.get(detail.id) : undefined);

  /**
   * `media` holds two things now: recordings and scores. They are split here
   * rather than in two queries because a piece has a handful of rows, and one
   * list means the panel's section counts cannot disagree with each other.
   */
  const scores = $derived(detail ? detail.media.filter((row) => row.kind === 'score') : []);
  const recordings = $derived(detail ? detail.media.filter((row) => row.kind !== 'score') : []);
  const openScore = $derived(scores.find((row) => row.id === openScoreId) ?? null);

  const pendingInDetail = $derived(
    recordings.filter((row) => row.state === 'pending').length,
  );

  const totals = $derived({
    minutes: pieces.reduce((sum, piece) => sum + piece.logged_minutes, 0),
    recordings: pieces.reduce((sum, piece) => sum + piece.recording_count, 0),
    scores: pieces.reduce((sum, piece) => sum + piece.score_count, 0),
  });

  $effect(() => {
    void load();
  });
</script>

<section class="card panel">
  <div class="spread wrap">
    <div>
      <h2>Repertoire</h2>
      <p class="muted small">
        Your pieces, what you have written about them, and your recordings — the
        library the sight-reading side can build exercises around.
      </p>
    </div>
    {#if status}
      <div class="row wrap">
        <span class="pill mono">{status.pieces} pieces</span>
        <span class="pill mono">{status.composers} composers</span>
        <span class="pill mono">{totals.recordings} recordings</span>
        {#if totals.scores > 0}
          <span class="pill mono">{totals.scores} scores</span>
        {/if}
        {#if totals.minutes > 0}
          <span class="pill mono">{totals.minutes} min logged</span>
        {/if}
        {#if status.media_pending > 0}
          <span class="pill warn">{status.media_pending} not copied</span>
        {/if}
        {#if status.media_missing > 0}
          <span class="pill bad">{status.media_missing} file missing</span>
        {/if}
      </div>
    {/if}
  </div>

  {#if error}
    <div class="error-banner">{error}</div>
  {/if}

  {#if editing}
    {#key editing === 'new' ? 'new' : editing.id}
      <PieceEditor
        piece={editing === 'new' ? null : editing}
        {composers}
        onSaved={(saved) => void afterWrite(saved.id)}
        onCancel={() => (editing = null)}
      />
    {/key}
  {/if}

  {#if loading && !status}
    <p class="muted small">Loading the library…</p>
  {:else if status?.pieces === 0}
    <div class="empty">
      <h3>The library is empty</h3>
      {#if status.legacy_found}
        <p class="muted small">
          Found a <code>piano-progress</code> database at <code>{status.legacy_db}</code>. Importing
          reads it and never writes to it, and can be run again later to pick up
          anything you add there in the meantime.
        </p>
        <div class="row wrap">
          <button class="primary" onclick={() => void runImport()} disabled={importing}>
            {importing ? 'Importing…' : 'Import from piano-progress'}
          </button>
          <label class="check">
            <input type="checkbox" bind:checked={copyMedia} />
            Copy the recordings into this app
          </label>
        </div>
      {:else}
        <p class="muted small">
          No <code>piano-progress</code> database at <code>{status.legacy_db}</code>. Set
          <code>SRT_LEGACY_DB</code> if yours lives elsewhere.
        </p>
      {/if}

      <div class="row wrap start-fresh">
        <span class="muted small">Or start from scratch:</span>
        <button class="primary" onclick={() => (editing = 'new')}>New piece</button>
      </div>

      {#if importReport}
        <div class="report">
          <strong>Imported</strong> {importReport.pieces} pieces,
          {importReport.composers} composers, {importReport.journal_entries} journal entries and
          {importReport.media_rows} recordings{#if importReport.media_copied}, copying
            {importReport.media_copied} files{/if}.
          {#if importReport.media_missing > 0}
            <span class="warn-text">{importReport.media_missing} recording file(s) were missing.</span>
          {/if}
        </div>
      {/if}
    </div>
  {:else}
    <div class="filters">
      <input
        type="search"
        placeholder="Search title, composer or opus…"
        bind:value={search}
        aria-label="Search the library"
      />
      <select bind:value={statusFilter} aria-label="Filter by status">
        <option value="">Any status</option>
        <option value="active">Active</option>
        <option value="completed">Completed</option>
        <option value="paused">Paused</option>
      </select>
      <select bind:value={composerFilter} aria-label="Filter by composer">
        <option value="">Any composer</option>
        {#each composers as composer (composer.id)}
          <option value={String(composer.id)}>{composer.name}</option>
        {/each}
      </select>
      <select bind:value={grouping} aria-label="Group by">
        <option value="composer">Group by composer</option>
        <option value="difficulty">Group by difficulty</option>
        <option value="none">No grouping</option>
      </select>
      <span class="muted small">{visible.length} shown</span>
      <button class="primary" onclick={() => (editing = 'new')}>New piece</button>
    </div>

    <div class="split" class:with-detail={detail !== null}>
      <div class="list">
        {#each groups as group (group.label)}
          {#if group.label}
            <h4 class="group">{group.label}</h4>
          {/if}
          {#each group.rows as piece (piece.id)}
            <button
              class="row-piece"
              class:selected={detail?.id === piece.id}
              aria-expanded={detail?.id === piece.id}
              onclick={() => void open(piece.id)}
            >
              <span class="title">
                {piece.title}
                {#if piece.opus}<span class="muted opus">{piece.opus}</span>{/if}
              </span>
              <span class="meta">
                {#if piece.key}<span class="tag">{piece.key}</span>{/if}
                {#if piece.difficulty}<span class="tag">{piece.difficulty}</span>{/if}
                <span class="tag" class:done={piece.status === 'completed'}>{piece.status}</span>
              </span>
              <span class="counts muted mono">
                {#if piece.journal_entries}✎ {piece.journal_entries}{/if}
                {#if piece.recording_count}♪ {piece.recording_count}{/if}
                {#if piece.score_count}𝄞 {piece.score_count}{/if}
              </span>
            </button>
          {/each}
        {/each}

        {#if visible.length === 0}
          <p class="muted small">Nothing matches those filters.</p>
        {/if}
      </div>

      {#if detailLoading}
        <div class="detail card"><p class="muted small">Loading…</p></div>
      {:else if detail}
        <div class="detail card">
          <div class="spread wrap">
            <div>
              <h3 class="detail-title">{detail.title}</h3>
              <p class="muted small">
                {detail.composer_name ?? 'Unknown composer'}{#if detail.opus} · {detail.opus}{/if}
                {#if detail.started_on} · started {detail.started_on}{/if}
              </p>
              <div class="row wrap detail-meta">
                {#if detail.key}<span class="pill">{detail.key}</span>{/if}
                {#if detail.difficulty}<span class="pill">{detail.difficulty}</span>{/if}
                <span class="pill" class:good={detail.status === 'completed'}>{detail.status}</span>
              </div>
            </div>
            <div class="row">
              <button onclick={() => (editing = detail)}>Edit</button>
              {#if confirmingDelete}
                <button class="danger" onclick={() => void removePiece()}>
                  Delete for good
                </button>
                <button class="ghost" onclick={() => (confirmingDelete = false)}>Keep</button>
              {:else}
                <button
                  class="ghost"
                  disabled={!app.host?.loopback}
                  title={app.host?.loopback ? '' : 'Only on the piano machine'}
                  onclick={() => (confirmingDelete = true)}>Delete</button
                >
              {/if}
              <button class="ghost" onclick={() => (detail = null)}>Close</button>
            </div>
          </div>

          {#if confirmingDelete}
            <div class="notice">
              Deleting removes the piece, its
              {detail.journal.length} journal {detail.journal.length === 1 ? 'entry' : 'entries'} and
              its {detail.media.length} catalogue {detail.media.length === 1 ? 'row' : 'rows'}.
              <strong>Recording and score files are left on disk.</strong>
            </div>
          {/if}

          {#if detail.description}
            <p class="description">{detail.description}</p>
          {/if}

          {#if suggestion}
            <div class="suggestion">
              <strong>Sight-reading fit</strong>
              {#if suggestion.suggested_key}
                <span class="pill accent">{suggestion.suggested_key}</span>
              {:else}
                <span class="pill">key not mapped</span>
              {/if}
              {#if suggestion.suggested_level}
                <span class="pill">starting level {suggestion.suggested_level}</span>
              {/if}
              {#if suggestion.suggested_key}
                <button
                  onclick={() => {
                    if (!detail) return;
                    app.pinKey(suggestion.suggested_key, detail.title);
                    app.view = 'practice';
                  }}
                >
                  Practise in {suggestion.suggested_key}
                </button>
              {/if}
              {#if suggestion.notes.length > 0}
                <span class="muted small">{suggestion.notes.join('; ')}</span>
              {/if}
            </div>
          {/if}

          <h4>Logged practice</h4>
          {#if practice && (practice.segments > 0 || practice.journal_minutes > 0)}
            <div class="row wrap practice-totals">
              <span class="pill accent" title="Time measured from MIDI, attributed to this piece">
                {formatMinutes(practice.minutes)} played
              </span>
              <span class="pill">{practice.segments} segments</span>
              <span class="pill">{practice.notes} notes</span>
              {#if practice.last_played}
                <span class="muted small">last played {practice.last_played}</span>
              {/if}
              {#if practice.journal_minutes > 0}
                <span
                  class="muted small"
                  title="Minutes written in the journal — a claim, not a measurement"
                >
                  {practice.journal_minutes} min written down
                </span>
              {/if}
            </div>
            {#if practice.tempo.points.length > 1}
              <div class="tempo">
                <span class="muted small">
                  Tempo over time (note rate at each logged segment — comparable with
                  itself, not a metronome reading)
                </span>
                <LineChart
                  yMin={Math.max(
                    0,
                    Math.min(...practice.tempo.points.map((point) => point.median_tempo)) - 20,
                  )}
                  yMax={Math.max(...practice.tempo.points.map((point) => point.median_tempo)) + 20}
                  yLabel="Tempo over time"
                  series={[
                    {
                      label: 'BPM',
                      color: 'var(--accent)',
                      points: practice.tempo.points.map((point) => ({
                        x: new Date(`${point.date}T00:00:00`).getTime(),
                        y: point.median_tempo,
                      })),
                    },
                  ]}
                  height={150}
                />
              </div>
            {/if}
          {:else}
            <p class="muted small">
              Nothing logged yet. Play with the Log tab's capture on and this fills itself.
            </p>
          {/if}

          <h4>Journal <span class="muted">({detail.journal.length})</span></h4>
          {#if detail.journal.length === 0}
            <p class="muted small">No entries yet.</p>
          {:else}
            <ul class="journal">
              {#each detail.journal as entry (entry.id)}
                <li data-journal-entry={entry.id}>
                  <div class="entry-head">
                    <span>
                      <span class="date mono">{entry.entry_date}</span>
                      {#if entry.practice_minutes}
                        <span class="pill">{entry.practice_minutes} min</span>
                      {/if}
                      {#if entry.sitting_id}
                        <span
                          class="muted small"
                          title="Written about the sitting you played, from the Log tab"
                          >about a logged session</span
                        >
                      {/if}
                    </span>
                    <span class="row">
                      {#if editingEntry === entry.id}
                        <button
                          class="ghost tiny"
                          disabled={savingJournal || !editContent.trim()}
                          onclick={() => void saveEdit(entry)}>Save entry</button
                        >
                        <button class="ghost tiny" onclick={cancelEditing}>Discard</button>
                      {:else}
                        <button
                          class="ghost tiny"
                          data-journal-edit={entry.id}
                          onclick={() => startEditing(entry)}>Edit entry</button
                        >
                        <button
                          class="ghost tiny"
                          disabled={!app.host?.loopback}
                          title={app.host?.loopback
                            ? 'Delete this entry'
                            : 'Only on the piano machine'}
                          onclick={() => void removeJournalEntry(entry)}>×</button
                        >
                      {/if}
                    </span>
                  </div>
                  {#if editingEntry === entry.id}
                    <div class="journal-edit">
                      <input type="date" bind:value={editDate} aria-label="Edit entry date" />
                      <input
                        type="number"
                        min="0"
                        max="1440"
                        placeholder="min"
                        bind:value={editMinutes}
                        aria-label="Edit practice minutes"
                      />
                      <textarea
                        rows="4"
                        bind:value={editContent}
                        aria-label="Edit journal entry"
                      ></textarea>
                    </div>
                  {:else}
                    <p class="entry-body">{entry.content}</p>
                  {/if}
                </li>
              {/each}
            </ul>
          {/if}


          <form
            class="journal-form"
            onsubmit={(event) => {
              event.preventDefault();
              void addJournalEntry();
            }}
          >
            {#if journalSitting !== null}
              <p class="muted small measured" data-journal-sitting={journalSitting}>
                About the session you just played{#if journalMeasured}: {journalMeasured}{/if}.
                <button
                  type="button"
                  class="ghost tiny"
                  onclick={() => {
                    journalSitting = null;
                    journalMeasured = null;
                  }}>Write about the piece instead</button
                >
              </p>
            {/if}
            <div class="row">
              <input type="date" bind:value={journalDate} aria-label="Entry date" required />
              <input
                type="number"
                min="0"
                max="1440"
                placeholder="min"
                bind:value={journalMinutes}
                aria-label="Practice minutes"
              />
            </div>
            <textarea
              rows="3"
              placeholder="What happened in this session?"
              bind:value={journalContent}
              aria-label="Journal entry"
              required
            ></textarea>
            <button type="submit" disabled={savingJournal || !journalContent.trim()}>
              {savingJournal ? '…' : 'Add'}
            </button>
          </form>

          <h4>Scores <span class="muted">({scores.length})</span></h4>
          <p class="muted small">
            The edition you actually play from — a PDF as it was published, or
            MusicXML engraved here. Kept with the piece, so it is on the piano
            machine and on anything that can reach it.
          </p>
          {#if scores.length === 0}
            <p class="muted small">None attached.</p>
          {:else}
            <ul class="scores">
              {#each scores as score (score.id)}
                <li>
                  <div class="rec-head">
                    <span class="rec-name">
                      {score.title ?? score.original_name ?? score.file_name}
                    </span>
                    <span class="row">
                      <span class="pill mono" data-score-codec={score.codec}>
                        {score.codec ?? 'score'}
                      </span>
                      <button
                        class="ghost tiny"
                        onclick={() => (openScoreId = openScoreId === score.id ? null : score.id)}
                      >
                        {openScoreId === score.id ? 'Hide' : 'View'}
                      </button>
                      <button
                        class="ghost tiny"
                        disabled={!app.host?.loopback}
                        title={app.host?.loopback
                          ? 'Remove this score from the library'
                          : 'Only on the piano machine'}
                        onclick={() => void removeScore(score.id)}>×</button
                      >
                    </span>
                  </div>
                  <p class="muted small mono">
                    {formatSize(score.size_bytes)}{#if score.taken_on} · {score.taken_on}{/if}
                  </p>
                  {#if openScoreId === score.id && openScore}
                    <ScoreViewer score={openScore} />
                  {/if}
                </li>
              {/each}
            </ul>
          {/if}

          <form
            class="upload"
            onsubmit={(event) => {
              event.preventDefault();
              void attachScore();
            }}
          >
            <input
              type="file"
              accept="application/pdf,.pdf,.musicxml,.xml"
              aria-label="Score file"
              bind:this={scoreInput}
              onchange={(event) => {
                const input = event.currentTarget as HTMLInputElement;
                scoreFile = input.files?.[0] ?? null;
                scoreNote = null;
              }}
            />
            <input
              placeholder="Title (optional)"
              bind:value={scoreTitle}
              aria-label="Score title"
            />
            <button class="primary" type="submit" disabled={attachingScore || !scoreFile}>
              {attachingScore ? 'Attaching…' : 'Attach score'}
            </button>
          </form>
          {#if scoreNote}
            <div class="notice">{scoreNote}</div>
          {/if}

          <TakeList
            takes={recordings.filter((row) => row.source === 'captured')}
            {segments}
            onloop={(mediaId, loop) => void saveLoop(mediaId, loop)}
            ondelete={(mediaId) => void removeRecording(mediaId)}
          />

          <h4>Recordings <span class="muted">({recordings.length})</span></h4>
          {#if recordings.length === 0}
            <p class="muted small">None attached.</p>
          {:else}
            {#if pendingInDetail > 0}
              <div class="notice">
                {pendingInDetail} of these play from the old <code>piano-progress</code> library.
                Copying them in makes this app self-contained.
                <button
                  onclick={() => void runImport()}
                  disabled={importing}
                  style="margin-left: 0.5rem"
                >
                  {importing ? 'Copying…' : 'Copy recordings in'}
                </button>
              </div>
            {/if}

            <ul class="recordings">
              {#each recordings as recording (recording.id)}
                <li>
                  <div class="rec-head">
                    <span class="rec-name">
                      {recording.title ?? recording.original_name ?? recording.file_name}
                    </span>
                    <span class="row">
                      {#if recording.state === 'present'}
                        <span class="pill good">in library</span>
                      {:else if recording.state === 'pending'}
                        <span class="pill">not copied yet</span>
                      {:else}
                        <span class="pill bad">file missing</span>
                      {/if}
                      <button
                        class="ghost tiny"
                        disabled={!app.host?.loopback}
                        title={app.host?.loopback
                          ? 'Remove this recording from the library'
                          : 'Only on the piano machine'}
                        onclick={() => void removeRecording(recording.id)}>×</button
                      >
                    </span>
                  </div>

                  {#if recording.state === 'missing'}
                    <p class="muted small">
                      The file is in neither the media directory nor the legacy
                      library, so it cannot be played.
                    </p>
                  {:else}
                    <RecordingPlayer
                      {recording}
                      onLoop={(next) => void saveLoop(recording.id, next)}
                    />
                  {/if}

                  <p class="muted small mono">
                    {formatDuration(recording.duration_secs)} · {formatSize(recording.size_bytes)} ·
                    {recording.codec ?? 'unknown codec'}{#if recording.taken_on} · {recording.taken_on}{/if}
                  </p>
                </li>
              {/each}
            </ul>
          {/if}

            <form
              class="upload"
              onsubmit={(event) => {
                event.preventDefault();
                void importRecording();
              }}
            >
              <input
                type="file"
                accept="audio/*,video/*"
                aria-label="Recording file"
                bind:this={fileInput}
                onchange={(event) => {
                  const input = event.currentTarget as HTMLInputElement;
                  uploadFile = input.files?.[0] ?? null;
                  uploadNote = null;
                }}
              />
              <input
                placeholder="Title (optional)"
                bind:value={uploadTitle}
                aria-label="Recording title"
              />
              <button class="primary" type="submit" disabled={uploading || !uploadFile}>
                {uploading ? 'Converting…' : 'Import recording'}
              </button>
            </form>
            {#if uploading}
              <p class="muted small">
                Probing and re-encoding with ffmpeg. A long recording can take a
                little while.
              </p>
            {/if}
            {#if uploadNote}
              <div class="notice">{uploadNote}</div>
            {/if}
        </div>
      {:else}
        <!-- The other direction round: the journal of the whole library, found by
             what it says rather than by which piece it belongs to. It is also what
             the detail pane shows when nothing is selected, which used to be blank. -->
        <div class="detail card" data-journal-feed>
          <h3>Recent notes</h3>
          <p class="muted small">
            The newest journal entries across the library. Pick a piece to read or add its
            own.
          </p>
          <input
            type="search"
            placeholder="Search the journal…"
            bind:value={feedSearch}
            aria-label="Search the journal"
          />
          {#if feedEntries.length === 0}
            <p class="muted small">
              {feedSearch ? 'No entries mention that.' : 'Nothing written down yet.'}
            </p>
          {:else}
            <ul class="journal feed">
              {#each feedEntries as entry (entry.id)}
                <li data-feed-entry={entry.id}>
                  <div class="entry-head">
                    <span>
                      <span class="date mono">{entry.entry_date}</span>
                      <button class="ghost tiny piece-link" onclick={() => void open(entry.piece_id)}>
                        {entry.piece_title}{entry.composer_name
                          ? ` · ${entry.composer_name}`
                          : ''}
                      </button>
                    </span>
                    {#if entry.practice_minutes}
                      <span class="pill">{entry.practice_minutes} min</span>
                    {/if}
                  </div>
                  <p class="entry-body">{entry.content}</p>
                </li>
              {/each}
            </ul>
          {/if}
        </div>
      {/if}
    </div>
  {/if}
</section>

<style>
  .panel {
    padding: 0.9rem 1rem;
    display: flex;
    flex-direction: column;
    gap: 0.7rem;
  }

  .panel p {
    margin: 0.2rem 0 0;
    line-height: 1.5;
    max-width: 70ch;
  }

  .small {
    font-size: 0.82rem;
  }

  .empty {
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
    align-items: flex-start;
  }

  .check {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    font-size: 0.85rem;
    color: var(--muted);
  }

  .report {
    background: var(--good-soft);
    border: 1px solid var(--good-line);
    color: var(--good);
    border-radius: var(--radius);
    padding: 0.6rem 0.75rem;
    font-size: 0.85rem;
  }

  .warn-text {
    color: var(--warn);
  }

  .filters {
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem;
    align-items: center;
    border: 1px solid var(--line);
    background: var(--surface-2);
    border-radius: var(--radius);
    padding: 0.5rem 0.6rem;
  }

  .filters input[type='search'] {
    font: inherit;
    flex: 1 1 14rem;
    min-width: 10rem;
    padding: 0.4rem 0.55rem;
    border-radius: 8px;
    border: 1px solid var(--line);
    background: var(--surface);
    color: var(--ink);
  }

  .split {
    display: grid;
    gap: 0.75rem;
    grid-template-columns: minmax(0, 1fr);
  }

  @media (min-width: 62rem) {
    .split.with-detail {
      grid-template-columns: minmax(0, 1fr) minmax(0, 1.15fr);
    }
  }

  .list {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
    max-height: 34rem;
    overflow-y: auto;
  }

  .group {
    margin: 0.6rem 0 0.2rem;
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--muted);
  }

  .row-piece {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto auto;
    gap: 0.5rem;
    align-items: center;
    text-align: left;
    padding: 0.45rem 0.55rem;
    border-radius: 8px;
    border: 1px solid transparent;
    background: var(--surface-2);
  }

  .row-piece:hover {
    border-color: var(--line);
  }

  .row-piece.selected {
    background: var(--accent-soft);
    border-color: var(--accent-line);
  }

  .title {
    font-weight: 600;
    font-size: 0.9rem;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .opus {
    font-weight: 400;
    font-size: 0.78rem;
    margin-left: 0.35rem;
  }

  .meta {
    display: flex;
    gap: 0.25rem;
    flex-wrap: wrap;
  }

  .tag {
    font-size: 0.7rem;
    padding: 0.05rem 0.4rem;
    border-radius: 999px;
    background: var(--surface);
    border: 1px solid var(--line);
    color: var(--muted);
    white-space: nowrap;
  }

  .tag.done {
    color: var(--good);
    border-color: var(--good-line);
  }

  .counts {
    font-size: 0.75rem;
    white-space: nowrap;
  }

  .detail {
    padding: 0.8rem 0.9rem;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    align-self: start;
    max-height: 40rem;
    overflow-y: auto;
  }

  .detail-meta {
    margin-top: 0.35rem;
  }

  .detail-title {
    font-size: 1.05rem;
    text-transform: none;
    letter-spacing: normal;
    color: var(--ink);
  }

  .description {
    font-size: 0.88rem;
  }

  .suggestion {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.35rem;
    background: var(--surface-2);
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: 0.5rem 0.6rem;
    font-size: 0.85rem;
  }

  .notice {
    background: var(--warn-soft);
    border: 1px solid var(--warn-line);
    color: var(--warn);
    border-radius: var(--radius);
    padding: 0.5rem 0.65rem;
    font-size: 0.83rem;
    line-height: 1.5;
  }

  .practice-totals {
    gap: 0.4rem;
  }

  .tempo {
    display: flex;
    flex-direction: column;
    gap: 0.3rem;
    margin-bottom: 0.3rem;
  }

  .start-fresh {
    border-top: 1px solid var(--line);
    padding-top: 0.6rem;
    margin-top: 0.2rem;
  }

  .recordings,
  .scores {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 0.7rem;
  }

  .recordings li,
  .scores li {
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: 0.5rem 0.6rem;
    background: var(--surface-2);
  }

  .rec-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
    margin-bottom: 0.35rem;
  }

  .rec-name {
    font-size: 0.85rem;
    font-weight: 600;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .upload {
    display: flex;
    gap: 0.3rem;
    align-items: center;
    flex-wrap: wrap;
    margin-bottom: 0.5rem;
  }

  .upload input[type='file'] {
    font-size: 0.8rem;
    max-width: 15rem;
  }

  .upload input[placeholder='Title (optional)'] {
    font: inherit;
    font-size: 0.84rem;
    padding: 0.3rem 0.4rem;
    border-radius: 7px;
    border: 1px solid var(--line);
    background: var(--surface);
    color: var(--ink);
  }

  .danger {
    background: var(--bad);
    border-color: var(--bad);
    color: #fff;
  }

  .ghost.tiny {
    padding: 0 0.35rem;
    font-size: 0.9rem;
    line-height: 1.4;
  }

  .entry-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.4rem;
  }

  /* Prose needs to keep its own line breaks, which an <input> could not hold at
     all. The box is a paragraph until you ask to change it, so reading the journal
     does not look like filling in a form. */
  .entry-body {
    white-space: pre-wrap;
    margin: 0.25rem 0 0;
  }

  /* In the cross-piece feed the piece is the thing you came for, so it reads as the
     link it is rather than as a caption. */
  .piece-link {
    padding: 0 0.2rem;
    font-size: 0.78rem;
    color: var(--accent);
  }

  .journal-form {
    display: flex;
    flex-direction: column;
    gap: 0.3rem;
    align-items: stretch;
    margin-top: 0.35rem;
  }

  .journal-form .row,
  .journal-edit {
    display: flex;
    gap: 0.3rem;
    align-items: center;
  }

  .journal-edit {
    flex-wrap: wrap;
    margin-top: 0.3rem;
  }

  .journal-edit textarea {
    flex: 1 1 100%;
  }

  .measured {
    margin: 0;
  }

  .journal-form input,
  .journal-form textarea,
  .journal-edit input,
  .journal-edit textarea {
    font: inherit;
    font-size: 0.84rem;
    padding: 0.3rem 0.4rem;
    border-radius: 7px;
    border: 1px solid var(--line);
    background: var(--surface);
    color: var(--ink);
    min-width: 0;
  }

  .journal-form textarea,
  .journal-edit textarea {
    resize: vertical;
    line-height: 1.4;
  }

  .journal {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  .journal li {
    border-left: 2px solid var(--line);
    padding-left: 0.6rem;
  }

  .journal p {
    margin: 0.15rem 0 0;
    font-size: 0.88rem;
  }

  .date {
    font-size: 0.78rem;
    color: var(--muted);
    margin-right: 0.3rem;
  }

  h4 {
    font-size: 0.78rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--muted);
    margin: 0.5rem 0 0.1rem;
  }
</style>
