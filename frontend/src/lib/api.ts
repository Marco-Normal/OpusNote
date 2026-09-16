/**
 * Typed client for the trainer API.
 *
 * The client never generates music or scores a performance itself — every
 * musical judgement comes from the backend. That is what lets the generator and
 * the scorer be replaced without touching the browser code.
 */

import type {
  AnalyticsSummary,
  AutotagReport,
  CaptureStatus,
  Composer,
  Exercise,
  HostInfo,
  IdentificationQuality,
  ImportReport,
  PieceDetail,
  PiecePracticeDetail,
  PerformanceDetail,
  PianoDownloadReport,
  PianoStatus,
  PieceSummary,
  PracticeImportReport,
  PracticeSource,
  PracticeStatus,
  PlayedNote,
  PracticeMode,
  DeleteResult,
  JournalEntry,
  JournalInput,
  PieceInput,
  PracticeSuggestion,
  Profile,
  Recording,
  RepertoireStatus,
  RatingHistory,
  ScoreResult,
  SegmentSummary,
  SittingDetail,
  SittingNotes,
  SittingSummary,
  SystemStatus,
  SkillInfo,
  Stats,
  TempoSeries,
  Workout,
  WorkoutHome,
} from './types';

const BASE = '/api';

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly detail?: unknown,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...init,
    });
  } catch (cause) {
    throw new ApiError(
      'Cannot reach the trainer API. Is the backend running on port 8000?',
      0,
      cause,
    );
  }

  await throwIfFailed(response, path);

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

async function throwIfFailed(response: Response, path: string): Promise<void> {
  if (response.ok) return;
  // Read the body once. Calling json() and then text() on failure throws
  // "body stream already read" and hides the server's actual message, which is
  // exactly the moment you most need it.
  const raw = await response.text();
  let detail: unknown = raw;
  try {
    detail = JSON.parse(raw);
  } catch {
    // Not JSON; keep the raw text.
  }
  const serverDetail =
    typeof detail === 'object' && detail !== null && 'detail' in detail
      ? String((detail as { detail: unknown }).detail)
      : raw.slice(0, 300);
  throw new ApiError(
    `Request to ${path} failed (${response.status})${serverDetail ? `: ${serverDetail}` : ''}`,
    response.status,
    detail,
  );
}

/**
 * POST a FormData body.
 *
 * Separate from `request` because the Content-Type must be left unset: the
 * browser has to add the multipart boundary, and setting the header by hand
 * produces a body the server cannot parse.
 */
async function requestForm<T>(path: string, form: FormData): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, { method: 'POST', body: form });
  } catch (cause) {
    throw new ApiError(
      'Cannot reach the trainer API. Is the backend running on port 8000?',
      0,
      cause,
    );
  }
  await throwIfFailed(response, path);
  return (await response.json()) as T;
}

export const api = {
  health: () => request<{ status: string; database: string; exercises: number; performances: number }>('/health'),

  /**
   * Where this request came from and what the server can see.
   *
   * Used to explain what this page can and cannot do: MIDI only exists on the piano
   * machine, and the irreversible actions are refused anywhere else.
   */
  host: () => request<HostInfo>('/host'),

  profile: () => request<Profile>('/profile'),

  resetProfile: () => request<Profile>('/profile/reset', { method: 'POST' }),

  skills: () => request<SkillInfo[]>('/skills'),

  nextExercise: (options: { skill?: string; bars?: number; key?: string } = {}) => {
    const params = new URLSearchParams();
    if (options.skill) params.set('skill', options.skill);
    if (options.bars) params.set('bars', String(options.bars));
    if (options.key) params.set('key', options.key);
    const query = params.toString();
    return request<Exercise>(`/exercise/next${query ? `?${query}` : ''}`);
  },

  exercise: (id: number) => request<Exercise>(`/exercise/${id}`),

  calibrationExercise: () => request<Exercise>('/calibration/next'),

  score: (payload: {
    exercise_id: number;
    notes: PlayedNote[];
    mode?: PracticeMode;
    latency_ms?: number;
    calibration?: boolean;
  }) => request<ScoreResult>('/score', { method: 'POST', body: JSON.stringify(payload) }),

  stats: () => request<Stats>('/stats'),

  /** Database size, media states, backup age, sequencer, capture. */
  systemStatus: () => request<SystemStatus>('/status/system'),

  /** Every rating change in the window, grouped by skill. */
  progressRatings: (days = 90) => request<RatingHistory>(`/progress/ratings?days=${days}`),

  /** One past attempt, in the same shapes the results panel uses. */
  performance: (id: number) => request<PerformanceDetail>(`/performances/${id}`),

  repertoire: {
    status: () => request<RepertoireStatus>('/repertoire/status'),

    pieces: (filters: { status?: string; composerId?: number; search?: string } = {}) => {
      const params = new URLSearchParams();
      if (filters.status) params.set('status', filters.status);
      if (filters.composerId !== undefined) params.set('composer_id', String(filters.composerId));
      if (filters.search) params.set('search', filters.search);
      const query = params.toString();
      return request<PieceSummary[]>(`/repertoire/pieces${query ? `?${query}` : ''}`);
    },

    piece: (id: number) => request<PieceDetail>(`/repertoire/pieces/${id}`),

    composers: () => request<Composer[]>('/repertoire/composers'),

    // The source path is server-side configuration, never a request parameter.
    importLegacy: (copyMedia: boolean) =>
      request<ImportReport>('/repertoire/import', {
        method: 'POST',
        body: JSON.stringify({ copy_media: copyMedia }),
      }),

    createPiece: (body: PieceInput) =>
      request<PieceDetail>('/repertoire/pieces', { method: 'POST', body: JSON.stringify(body) }),

    // PATCH semantics: only the keys present are changed, and an explicit null
    // clears a field. Send the object you mean.
    updatePiece: (id: number, body: Partial<PieceInput>) =>
      request<PieceDetail>(`/repertoire/pieces/${id}`, {
        method: 'PATCH',
        body: JSON.stringify(body),
      }),

    deletePiece: (id: number) =>
      request<DeleteResult>(`/repertoire/pieces/${id}`, { method: 'DELETE' }),

    createComposer: (body: { name: string; notes?: string | null }) =>
      request<Composer>('/repertoire/composers', { method: 'POST', body: JSON.stringify(body) }),

    deleteComposer: (id: number) =>
      request<DeleteResult>(`/repertoire/composers/${id}`, { method: 'DELETE' }),

    createJournal: (pieceId: number, body: JournalInput) =>
      request<JournalEntry>(`/repertoire/pieces/${pieceId}/journal`, {
        method: 'POST',
        body: JSON.stringify(body),
      }),

    updateJournal: (entryId: number, body: Partial<JournalInput>) =>
      request<JournalEntry>(`/repertoire/journal/${entryId}`, {
        method: 'PATCH',
        body: JSON.stringify(body),
      }),

    deleteJournal: (entryId: number) =>
      request<DeleteResult>(`/repertoire/journal/${entryId}`, { method: 'DELETE' }),

    /** The newest entries across the whole library, newest first. */
    journal: (filters: { limit?: number; search?: string } = {}) => {
      const query = new URLSearchParams();
      if (filters.limit) query.set('limit', String(filters.limit));
      if (filters.search) query.set('search', filters.search);
      return request<JournalEntry[]>(`/repertoire/journal${query.size ? `?${query}` : ''}`);
    },

    uploadRecording: (pieceId: number, file: File, title?: string) => {
      const form = new FormData();
      form.append('file', file);
      if (title) form.append('title', title);
      return requestForm<Recording>(`/repertoire/pieces/${pieceId}/media`, form);
    },

    updateRecording: (
      mediaId: number,
      body: {
        title?: string | null;
        piece_id?: number | null;
        loop_start_s?: number | null;
        loop_end_s?: number | null;
      },
    ) =>
      request<Recording>(`/repertoire/media/${mediaId}`, {
        method: 'PATCH',
        body: JSON.stringify(body),
      }),

    deleteRecording: (mediaId: number) =>
      request<DeleteResult>(`/repertoire/media/${mediaId}`, { method: 'DELETE' }),

    /**
     * Attach a score. Its own endpoint rather than the recording one: a score is
     * validated by its content and stored untouched, so it never reaches ffmpeg.
     */
    uploadScore: (pieceId: number, file: File, title?: string) => {
      const form = new FormData();
      form.append('file', file);
      if (title) form.append('title', title);
      return requestForm<Recording>(`/repertoire/pieces/${pieceId}/scores`, form);
    },

    /** Where a media row's bytes are served from, for an <audio>/<iframe>/fetch. */
    mediaUrl: (mediaId: number) => `/api/repertoire/media/${mediaId}/file`,
  },

  audio: {
    /** Is the sampled piano installed, and what is its licence? */
    pianoStatus: () => request<PianoStatus>('/audio/piano'),

    /** Fetch it once (about 2 MB). Safe to re-run: existing files are skipped. */
    downloadPiano: () =>
      request<PianoDownloadReport>('/audio/piano', { method: 'POST' }),
  },

  practice: {
    status: () => request<PracticeStatus>('/practice/status'),

    /** "I am still capturing." Sent every 15 s by whichever client is logging. */
    reportCapture: (body: { origin: string; enabled: boolean; pending: number }) =>
      request<CaptureStatus>('/practice/capture-status', {
        method: 'POST',
        body: JSON.stringify(body),
      }),

    /**
     * Send a batch of played notes. Absolute epoch ms; the server decides which
     * sitting they belong to.
     */
    ingest: (body: {
      source: PracticeSource;
      events: {
        epoch_ms: number;
        pitch: number;
        velocity: number;
        duration_ms: number;
        channel: number | null;
      }[];
      /**
       * Sustain-pedal moves. Optional on the wire: a batch with none is the
       * ordinary case, and a server that predates the field ignores it.
       */
      pedals?: { epoch_ms: number; value: number; channel: number | null }[];
    }) =>
      request<{ sitting_id: number | null; accepted: number; duplicates: number }>(
        '/practice/events',
        {
          method: 'POST',
          body: JSON.stringify({
            // Minutes east of UTC, which is what the server needs to file the
            // sitting under the player's calendar day.
            tz_offset_minutes: -new Date().getTimezoneOffset(),
            ...body,
          }),
        },
      ),

    sittings: (limit = 20) => request<SittingSummary[]>(`/practice/sittings?limit=${limit}`),

    /**
     * Finish the open sitting now, because the piano went away.
     *
     * Switching the piano off is a much sooner answer to "are they done?" than the
     * five-minute silence, and it means the dashboard shows the sitting at once.
     */
    closeSitting: () =>
      request<{ closed: boolean; sitting_id: number | null; reason: string | null }>(
        '/practice/sittings/close',
        { method: 'POST' },
      ),

    sitting: (id: number) => request<SittingDetail>(`/practice/sittings/${id}`),

    /** Every note of a sitting, read on demand: the only heavy payload here. */
    sittingNotes: (id: number) => request<SittingNotes>(`/practice/sittings/${id}/notes`),

    resegment: (id: number, confirm = false) =>
      request<SegmentSummary[]>(`/practice/sittings/${id}/resegment`, {
        method: 'POST',
        body: JSON.stringify({ confirm }),
      }),

    // PATCH semantics: `piece_id: null` clears a label rather than leaving it.
    assignSegment: (segmentId: number, pieceId: number | null) =>
      request<SegmentSummary[]>(`/practice/segments/${segmentId}`, {
        method: 'PATCH',
        body: JSON.stringify({ piece_id: pieceId }),
      }),

    splitSegment: (segmentId: number, atMs: number) =>
      request<SegmentSummary[]>(`/practice/segments/${segmentId}/split`, {
        method: 'POST',
        body: JSON.stringify({ at_ms: atMs }),
      }),

    mergeSegments: (segmentId: number, otherId: number) =>
      request<SegmentSummary[]>(`/practice/segments/${segmentId}/merge`, {
        method: 'POST',
        body: JSON.stringify({ other_id: otherId }),
      }),

    /**
     * Answer the question a match asks. Taking a *suggested* piece is an ordinary
     * assignment (`assignSegment`) — it was never written, so there is nothing to
     * overrule. These three are about a guess the matcher already made or offered.
     */
    identify: (segmentId: number, action: 'accept' | 'reject' | 'dismiss') =>
      request<SegmentSummary[]>(`/practice/segments/${segmentId}/identification`, {
        method: 'POST',
        body: JSON.stringify({ action }),
      }),

    /** Look for matches among the segments that are still unlabelled. */
    autotag: () => request<AutotagReport>('/practice/autotag', { method: 'POST' }),

    identificationQuality: () => request<IdentificationQuality>('/practice/autotag/quality'),

    summary: (days = 30) => request<AnalyticsSummary>(`/practice/analytics/summary?days=${days}`),

    tempo: (pieceId: number) => request<TempoSeries>(`/practice/analytics/tempo?piece_id=${pieceId}`),

    piece: (pieceId: number) => request<PiecePracticeDetail>(`/practice/pieces/${pieceId}`),

    importLegacy: () =>
      request<PracticeImportReport>('/practice/import-legacy', { method: 'POST' }),
  },

  workout: {
    home: () => request<WorkoutHome>('/workout'),

    current: () => request<Workout | null>('/workout/current'),

    start: (body: { target_skill?: string; bars?: number } = {}) =>
      request<Workout>('/workout/start', {
        method: 'POST',
        body: JSON.stringify({
          tz_offset_minutes: -new Date().getTimezoneOffset(),
          ...body,
        }),
      }),

    finish: (id: number) => request<Workout>(`/workout/${id}/finish`, { method: 'POST' }),
  },

  backup: {
    /** A plain URL: the endpoint sets Content-Disposition, so a link downloads it. */
    exportUrl: `${BASE}/backup/export`,

    import: (document: unknown, mode: 'merge' | 'replace', confirm: boolean) =>
      request<{ mode: string; written: Record<string, number>; total: number; counts: Record<string, number> }>(
        '/backup/import',
        { method: 'POST', body: JSON.stringify({ document, mode, confirm }) },
      ),
  },

  practiceSuggestions: () => request<PracticeSuggestion[]>('/practice-suggestions'),
};
