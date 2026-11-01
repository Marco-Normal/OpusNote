<script lang="ts">
  import { api } from '../lib/api';
  import { app } from '../lib/state.svelte';
  import PieceEditor from './PieceEditor.svelte';
  import type {
    Composer,
    ImportReport,
    JournalEntry,
    PieceDetail,
    PiecePractice,
    PieceSummary,
    PracticeSuggestion,
    RepertoireStatus,
    Recording,
    SegmentSummary,
  } from '../lib/types';
  import { formatDuration } from '../lib/clock';
  import { formatMinutes, formatSize } from '../lib/types';
  import type { PiecePracticeDetail } from '../lib/types';
  import LineChart from './LineChart.svelte';
  import ScoreViewer from './ScoreViewer.svelte';
  import RecordingPlayer from './RecordingPlayer.svelte';
  import PassageList from './PassageList.svelte';
  import TakeList from './TakeList.svelte';
  import type { Loop } from '../lib/waveform';

  import PieceList from './PieceList.svelte';
  import JournalSection from './JournalSection.svelte';

  let status = $state<RepertoireStatus | null>(null);
  let pieces = $state<PieceSummary[]>([]);
  let composers = $state<Composer[]>([]);
  let suggestions = $state<Map<number, PracticeSuggestion>>(new Map());
  let detail = $state<PieceDetail | null>(null);

  let loading = $state(true);
  let detailLoading = $state(false);
  /** A write that takes more than one request, so the controls that start it can wait. */
  let busy = $state(false);
  let error = $state<string | null>(null);
  let importing = $state(false);
  // null = closed, 'new' = creating, a PieceDetail = editing that piece.
  let editing = $state<PieceDetail | 'new' | null>(null);
  let confirmingDelete = $state(false);

  let savingJournal = $state(false);
  let journalSectionRef = $state<ReturnType<typeof JournalSection> | null>(null);

  // Set when the entry is being written about a sitting, from the Log tab.
  let journalSitting = $state<number | null>(null);
  let journalMeasured = $state<string | null>(null);
  // The newest entries across the library, shown where a piece would be.
  let feedEntries = $state<JournalEntry[]>([]);
  let feedSearch = $state('');
  let feedTimer: ReturnType<typeof setTimeout> | null = null;
  let feedTag = $state('');
  // The take the entry being written is about, set by the recording's own button.
  let journalTake = $state<number | null>(null);
  /** Per-piece logged minutes, the widest window the read allows, for the effort sorts. */
  let practiceByPiece = $state<PiecePractice[]>([]);

  $effect(() => {
    // Read `feedSearch` here so this re-runs when it changes, and pass the value into
    // the debounce so typing a word does not fire a query per keystroke.
    const term = feedSearch;
    const tag = feedTag;
    if (feedTimer) clearTimeout(feedTimer);
    feedTimer = setTimeout(() => void loadFeed(term, tag), 200);
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
      segments = new Map();
      return;
    }
    await show(pieceId);
  }

  /**
   * Load a piece without the click-to-close toggle.
   *
   * `open()` closes a row that is already open, which is right for a click and wrong for a
   * deep link: following `#/repertoire/piece/12` for the piece already on screen must leave
   * it open, not shut it.
   */
  async function show(pieceId: number): Promise<void> {
    detailLoading = true;
    error = null;
    try {
      const opened = await api.repertoire.piece(pieceId);
      detail = opened;
      practice = await api.practice.piece(pieceId).catch(() => null);
      await loadSegments(opened.media);
    } catch (cause) {
      error = cause instanceof Error ? cause.message : String(cause);
    } finally {
      detailLoading = false;
    }
  }

  // Open the piece a link asked for, once. `consumeEntity` clears the request, so this
  // cannot re-open something the player has since closed.
  $effect(() => {
    const id = app.consumeEntity('piece');
    if (id !== null) void show(id);
  });

  /**
   * The segments the open piece's takes were played in.
   *
   * The media rows are passed in rather than read back off `detail`: two `open()` calls can
   * overlap, and a loader that read the mutable detail would pair one piece's takes with another's
   * segments. Only the sittings that actually produced a take are fetched — a piece can hold
   * hundreds of segments across years of practice, and fetching them all to label two takes is the
   * wrong trade.
   */
  async function loadSegments(media: Recording[]): Promise<void> {
    const sittingIds = [
      ...new Set(
        media
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
      await loadSegments(detail.media);
    } else {
      detail = null;
      practice = null;
      segments = new Map();
    }
    editing = null;
    confirmingDelete = false;
    // The cross-piece feed is on screen whenever no piece is selected, so a write
    // from either side has to show up in it.
    void loadFeed(feedSearch, feedTag);
  }

  async function loadFeed(term: string, tag = ''): Promise<void> {
    try {
      feedEntries = await api.repertoire.journal({
        limit: 40,
        search: term || undefined,
        tag: tag || undefined,
      });
    } catch {
      // The feed is a convenience on an otherwise empty pane. A failure here must not
      // take the whole view over with an error about something the user did not ask
      // for; the pane simply stays empty.
      feedEntries = [];
    }
  }

  /** "coda, slow" → ["coda", "slow"]. The server trims and de-duplicates too. */
  /** The widest window the read allows, so "least time invested" means what it says. */
  async function loadPracticeByPiece(): Promise<void> {
    practiceByPiece = await api.practice.piecePractice(3650).catch(() => []);
  }

  async function applyBulk(selectedIds: number[], statusToApply: 'active' | 'paused' | 'completed'): Promise<void> {
    busy = true;
    try {
      for (const id of selectedIds) {
        await api.repertoire.updatePiece(id, { status: statusToApply });
      }
      await load();
    } catch (cause) {
      error = cause instanceof Error ? cause.message : String(cause);
    } finally {
      busy = false;
    }
  }

  /** Write a journal entry about a take: set the date and the link, then show the form. */
  function writeAboutTake(recordingId: number): void {
    journalSitting = null;
    journalTake = recordingId;
    journalSectionRef?.scrollFormIntoView();
  }

  function localDate(): string {
    const now = new Date();
    const local = new Date(now.getTime() - now.getTimezoneOffset() * 60_000);
    return local.toISOString().slice(0, 10);
  }

  async function addPassage(body: {
    start_bar: number;
    end_bar: number;
    label: string | null;
    source: 'manual' | 'loop';
    media_id: number | null;
  }): Promise<void> {
    if (!detail) return;
    try {
      await api.repertoire.createPassage(detail.id, body);
      await afterWrite(detail.id);
    } catch (cause) {
      error = cause instanceof Error ? cause.message : String(cause);
    }
  }

  async function markWorkedOn(passageId: number): Promise<void> {
    if (!detail) return;
    try {
      await api.repertoire.updatePassage(passageId, { last_worked_on: localDate() });
      await afterWrite(detail.id);
    } catch (cause) {
      error = cause instanceof Error ? cause.message : String(cause);
    }
  }

  async function removePassage(passageId: number): Promise<void> {
    if (!detail) return;
    try {
      await api.repertoire.deletePassage(passageId);
      await afterWrite(detail.id);
    } catch (cause) {
      error = cause instanceof Error ? cause.message : String(cause);
    }
  }

  async function addJournalEntry(data: {
    entry_date: string;
    content: string;
    practice_minutes: number | null;
    sitting_id: number | null;
    tags: string[];
    difficulty: number | null;
    fluency: number | null;
    media_id: number | null;
  }): Promise<void> {
    if (!detail || !data.content.trim()) return;
    savingJournal = true;
    error = null;
    try {
      const pieceId = detail.id;
      await api.repertoire.createJournal(pieceId, data);
      journalSitting = null;
      journalMeasured = null;
      journalTake = null;
      await afterWrite(pieceId);
    } catch (cause) {
      error = cause instanceof Error ? cause.message : String(cause);
    } finally {
      savingJournal = false;
    }
  }

  async function saveEdit(
    entry: JournalEntry,
    editData: {
      entry_date: string;
      content: string;
      practice_minutes: number | null;
      tags: string[];
      difficulty: number | null;
      fluency: number | null;
    },
  ): Promise<void> {
    if (!detail || !editData.content.trim()) return;
    savingJournal = true;
    error = null;
    try {
      await api.repertoire.updateJournal(entry.id, editData);
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
    void loadPracticeByPiece();
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
    <div class="split" class:with-detail={detail !== null}>
      <PieceList
        {pieces}
        {composers}
        {practiceByPiece}
        selectedPieceId={detail?.id ?? null}
        {busy}
        onSelectPiece={(id) => {
          app.reflect(
            detail?.id === id
              ? { name: 'repertoire' }
              : { name: 'repertoire', entity: { kind: 'piece', id } },
          );
          void open(id);
        }}
        onNewPiece={() => (editing = 'new')}
        onBulkUpdate={applyBulk}
      />

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
              <button
                class="ghost"
                onclick={() => {
                  detail = null;
                  app.reflect({ name: 'repertoire' });
                }}>Close</button
              >
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
                    app.navigate({ name: 'practice' });
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

          <JournalSection
            bind:this={journalSectionRef}
            {detail}
            {feedEntries}
            bind:feedTag
            bind:feedSearch
            {savingJournal}
            {journalSitting}
            {journalMeasured}
            {journalTake}
            onOpenPiece={(id) => void open(id)}
            onAddJournalEntry={addJournalEntry}
            onSaveJournalEntry={saveEdit}
            onRemoveJournalEntry={removeJournalEntry}
            onClearSittingDraft={() => {
              journalSitting = null;
              journalMeasured = null;
            }}
            onClearTakeDraft={() => {
              journalTake = null;
            }}
          />

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
                    <button
                      class="ghost tiny"
                      data-write-about-take={recording.id}
                      title="Write a journal entry about this recording"
                      onclick={() => writeAboutTake(recording.id)}>Write about this take</button
                    >
                  {/if}

                  <p class="muted small mono">
                    {formatDuration(recording.duration_secs)} · {formatSize(recording.size_bytes)} ·
                    {recording.codec ?? 'unknown codec'}{#if recording.taken_on} · {recording.taken_on}{/if}
                  </p>
                </li>
              {/each}
            </ul>
          {/if}

          <PassageList
            passages={detail.passages}
            {recordings}
            {busy}
            oncreate={(body) => void addPassage(body)}
            onworked={(id) => void markWorkedOn(id)}
            ondelete={(id) => void removePassage(id)}
          />

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
        <JournalSection
          bind:this={journalSectionRef}
          detail={null}
          {feedEntries}
          bind:feedTag
          bind:feedSearch
          {savingJournal}
          journalSitting={null}
          journalMeasured={null}
          journalTake={null}
          onOpenPiece={(id) => void open(id)}
          onAddJournalEntry={addJournalEntry}
          onSaveJournalEntry={saveEdit}
          onRemoveJournalEntry={removeJournalEntry}
          onClearSittingDraft={() => {}}
          onClearTakeDraft={() => {}}
        />
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

  h4 {
    font-size: 0.78rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--muted);
    margin: 0.5rem 0 0.1rem;
  }
</style>
