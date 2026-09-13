/**
 * Shared types mirroring the FastAPI schemas in `backend/app/models.py`.
 *
 * Keeping them in one file makes the API contract visible on the client side:
 * if the backend changes shape, this is the only file that needs to follow.
 */

export interface ExpectedNote {
  index: number;
  event_id: number;
  pitch: number;
  onset_q: number;
  duration_q: number;
  onset_s: number;
  hand: 'RH' | 'LH';
  measure: number;
  beat: number;
}

export interface MeasureMeta {
  measure: number;
  beats: number;
  beat_unit_q: number;
  bar_quarters: number;
}

export interface Exercise {
  exercise_id: number;
  musicxml: string;
  tempo_bpm: number;
  bars: number;
  key_name: string | null;
  meter: string | null;
  levels: Record<string, number>;
  difficulty_elo: number;
  target_skill: string | null;
  source: string;
  expected_notes: ExpectedNote[];
  measures: MeasureMeta[];
  /** Left-hand figure used, when the exercise has two hands. */
  bass_pattern: string | null;
  rationale: string | null;
  complete?: boolean | null;
  step?: number | null;
  total?: number | null;
}

export type NoteStatus = 'correct' | 'wrong_pitch' | 'missed' | 'pending' | 'extra';

export interface NoteFeedback {
  index: number;
  event_id: number;
  hand: 'RH' | 'LH';
  pitch: number;
  measure: number;
  beat: number;
  onset_s: number;
  status: NoteStatus;
  played_pitch: number | null;
  onset_error_s: number | null;
  onset_error_beats: number | null;
}

export interface RatingChange {
  skill: string;
  before: number | null;
  after: number | null;
  delta: number | null;
}

export interface SkillSnapshot {
  slug: string;
  name: string;
  rating: number;
  level: number;
  attempts: number;
  target_level: number | null;
}

export interface ScoreResult {
  performance_id: number;
  exercise_id: number;
  mode: PracticeMode;
  passed: boolean;
  score: number;
  pitch_accuracy: number;
  rhythm_accuracy: number;
  continuity_accuracy: number;
  counts: {
    expected: number;
    played: number;
    matched: number;
    wrong_pitch: number;
    missed: number;
    extra: number;
    hesitations: number;
  };
  timing: {
    mean_onset_error_beats: number;
    onset_error_std_beats: number;
  };
  by_hand: Record<string, { total: number; accuracy: number; wrong_pitch: number; missed: number }>;
  feedback: NoteFeedback[];
  target_skill: string | null;
  rating_change: RatingChange | null;
  skills: SkillSnapshot[];
  next_hint: string;
}

/** One rating change, and whether that skill was the attempt's focus. */
export interface RatingPoint {
  at: string;
  before: number;
  after: number;
  delta: number;
  score: number | null;
  performance_id: number | null;
  focus: boolean;
}

export interface SkillRatingSeries {
  slug: string;
  name: string;
  points: RatingPoint[];
}

export interface RatingHistory {
  days: number;
  skills: SkillRatingSeries[];
  biggest_gain: string | null;
  biggest_gain_delta: number;
}

/** A past attempt, with everything needed to show and replay it. */
export interface PerformanceDetail {
  performance_id: number;
  exercise_id: number;
  score: number | null;
  pitch_accuracy: number | null;
  rhythm_accuracy: number | null;
  continuity_accuracy: number | null;
  mode: string;
  tempo_bpm: number | null;
  performed_at: string | null;
  key_name: string | null;
  meter: string | null;
  difficulty_elo: number | null;
  target_skill: string | null;
  levels: Record<string, number>;
  expected_notes: ExpectedNote[];
  played_notes: PlayedNote[];
  feedback: NoteFeedback[];
  by_hand: Record<string, { total: number; accuracy: number }>;
}

export interface SkillInfo {
  slug: string;
  name: string;
  description: string | null;
  levels: string[] | null;
  rating: number | null;
  level: number | null;
  attempts: number | null;
  last_practiced_at: string | null;
}

export interface Profile {
  user_id: number;
  username: string;
  default_rating: number;
  pass_threshold: number;
  exercise_bars: number;
  calibration_total: number;
  calibration_step: number;
  ratings: Record<string, number>;
  levels: Record<string, number>;
}

export interface StatsSummary {
  performances: number;
  average_score: number;
  best_score: number;
  pass_rate: number;
  streak_days: number;
  calibration_complete: boolean;
  calibration_step: number;
  calibration_total: number;
}

export interface Stats {
  summary: StatsSummary;
  radar: {
    slug: string;
    name: string;
    rating: number;
    level: number;
    attempts: number;
    last_practiced_at: string | null;
  }[];
  history: {
    id: number;
    score: number;
    pitch_accuracy: number;
    rhythm_accuracy: number;
    continuity_accuracy: number;
    tempo_bpm: number;
    performed_at: string;
    target_skill: string | null;
    key_name: string | null;
    meter: string | null;
    mode: string;
    difficulty_elo: number;
  }[];
  tempo_progress: { date: string; tempo_bpm: number }[];
  common_mistakes: { kind: string; label: string; count: number }[];
  skills: { slug: string; name: string; description: string; levels: string[] }[];
  generated_at: string;
}

export interface PlayedNote {
  pitch: number;
  onset: number;
  duration: number;
  velocity: number;
  channel: number;
}

export type PracticeMode = 'practice' | 'performance';
export type AppView = 'practice' | 'calibrate' | 'stats' | 'log' | 'repertoire';

export const NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'] as const;

export function midiToName(pitch: number): string {
  return `${NOTE_NAMES[((pitch % 12) + 12) % 12]}${Math.floor(pitch / 12) - 1}`;
}

// --------------------------------------------------------------------------
// Repertoire — the piece library, its journal, and its recordings
// --------------------------------------------------------------------------

export interface JournalEntry {
  id: number;
  piece_id: number;
  entry_date: string;
  content: string;
  practice_minutes: number | null;
  created_at: string | null;
}

export interface Recording {
  id: number;
  piece_id: number | null;
  kind: string;
  file_name: string;
  original_name: string | null;
  title: string | null;
  duration_secs: number | null;
  size_bytes: number | null;
  codec: string | null;
  taken_on: string | null;
  /**
   * present  — copied into the ecosystem media directory
   * pending  — not copied yet, but playable from the legacy library
   * missing  — in neither place
   */
  state: 'present' | 'pending' | 'missing';
}

export interface PieceSummary {
  id: number;
  title: string;
  composer_id: number | null;
  composer_name: string | null;
  opus: string | null;
  difficulty: string | null;
  key: string | null;
  status: string;
  started_on: string | null;
  journal_entries: number;
  logged_minutes: number;
  recording_count: number;
}

export interface PieceDetail extends PieceSummary {
  description: string | null;
  created_at: string | null;
  journal: JournalEntry[];
  media: Recording[];
}

export interface Composer {
  id: number;
  name: string;
  notes: string | null;
  piece_count: number;
}

export interface RepertoireStatus {
  pieces: number;
  composers: number;
  journal_entries: number;
  media_rows: number;
  media_present: number;
  media_pending: number;
  media_missing: number;
  legacy_db: string;
  legacy_found: boolean;
  media_dir: string;
}

export interface ImportReport {
  source_db: string;
  source_found: boolean;
  composers: number;
  pieces: number;
  journal_entries: number;
  media_rows: number;
  media_copied: number;
  media_missing: number;
  media_pending: number;
  skipped: string[];
  notes: string[];
}

/** A piece mapped onto the sight-reading side: key spelling and starting level. */
export interface PracticeSuggestion {
  piece_id: number;
  title: string;
  composer_name: string | null;
  piece_key: string | null;
  suggested_key: string | null;
  difficulty: string | null;
  suggested_level: number | null;
  notes: string[];
}

// --------------------------------------------------------------------------
// Practice logging
// --------------------------------------------------------------------------

/** What produced a batch of notes. A closed set, matching the server's. */
export type PracticeSource = 'web_midi' | 'sight_reading';

export interface PracticeStatus {
  sittings: number;
  notes: number;
  first_date: string | null;
  last_date: string | null;
  /** True when the newest sitting is still receiving notes. */
  open_sitting: boolean;
  /** Epoch ms of the last note the server stored, or null. */
  last_note_ms: number | null;
  capture: CaptureStatus | null;
}

/** What a capturing client tells the server about itself. */
export interface CaptureStatus {
  origin: string;
  enabled: boolean;
  pending: number;
  at_ms: number;
}

/** Facts about where this page is being used from, and what the server can see. */
export interface HostInfo {
  /** The address this request arrived from, as the server sees it. */
  host: string | null;
  /** True when this page is on the machine running the server. */
  loopback: boolean;
  /** False means ALSA's sequencer is absent, so Web MIDI finds nothing at all. */
  sequencer: boolean;
  /** ALSA sequencer clients, e.g. ["Midi Through", "CASIO USB-MIDI"]. */
  clients: string[];
}

export interface SittingSummary {
  id: number;
  started_at: string;
  ended_at: string;
  local_date: string;
  source: string;
  note_count: number;
  duration_s: number;
  segment_count: number;
}

export interface SegmentMetrics {
  duration_s: number | null;
  note_count: number | null;
  /** Note rate as BPM over attacks — comparable with itself, not an absolute tempo. */
  median_tempo: number | null;
  mean_velocity: number | null;
  velocity_stddev: number | null;
  restarts: number | null;
}

export interface SegmentSummary {
  id: number;
  sitting_id: number;
  start_ms: number;
  end_ms: number;
  piece_id: number | null;
  piece_title: string | null;
  composer_name: string | null;
  source: string | null;
  workout_id: number | null;
  confidence: number | null;
  identified_by: string | null;
  note_count: number;
  metrics: SegmentMetrics | null;
}

/** One note as it was played, relative to the sitting's start. */
export interface LoggedNote {
  onset_ms: number;
  duration_ms: number;
  pitch: number;
  velocity: number;
  channel: number | null;
}

export interface SittingNotes {
  sitting_id: number;
  started_ms: number;
  notes: LoggedNote[];
}

export interface SittingDetail {
  id: number;
  started_at: string;
  ended_at: string;
  local_date: string;
  source: string;
  note_count: number;
  duration_s: number;
  closed: boolean;
  segments: SegmentSummary[];
}

export interface CalendarDay {
  date: string;
  minutes: number;
  notes: number;
  sittings: number;
}

export interface PiecePractice {
  piece_id: number;
  title: string;
  composer_name: string | null;
  minutes: number;
  notes: number;
  segments: number;
  last_played: string | null;
  journal_minutes: number;
}

export interface TempoPoint {
  date: string;
  median_tempo: number;
  segment_id: number;
}

export interface TempoSeries {
  piece_id: number;
  title: string;
  points: TempoPoint[];
}

export interface PiecePracticeDetail extends PiecePractice {
  tempo: TempoSeries;
}

export interface NeglectedPiece {
  piece_id: number;
  title: string;
  composer_name: string | null;
  days_since: number | null;
  last_played: string | null;
}

export interface SourceSplit {
  source: string;
  minutes: number;
  notes: number;
}

export interface AnalyticsSummary {
  days: number;
  total_minutes: number;
  total_notes: number;
  today_minutes: number;
  streak_days: number;
  calendar: CalendarDay[];
  by_piece: PiecePractice[];
  neglected: NeglectedPiece[];
  sources: SourceSplit[];
  recent: SittingSummary[];
  workouts_completed: number;
  workouts_this_week: number;
  last_note_ms: number | null;
  capture: CaptureStatus | null;
}

export interface PracticeImportReport {
  source_db: string;
  available: boolean;
  sittings: number;
  note_events: number;
  segments: number;
  note: string | null;
}

// --------------------------------------------------------------------------
// Workouts
// --------------------------------------------------------------------------

export interface Workout {
  id: number;
  started_ms: number;
  started_at: string;
  ended_ms: number | null;
  ended_at: string | null;
  local_date: string;
  target_skill: string | null;
  bars: number | null;
  planned: number | null;
  completed: boolean;
  running: boolean;
  sitting_id: number | null;
  exercises_done: number;
  minutes: number;
}

export interface WorkoutHome {
  current: Workout | null;
  recent: Workout[];
  workouts_completed: number;
  workouts_this_week: number;
  last_workout_date: string | null;
  window_days: number;
}

/** Human-readable duration for a recording length in seconds. */
export function formatDuration(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds)) return '—';
  const total = Math.round(seconds);
  const minutes = Math.floor(total / 60);
  const remainder = total % 60;
  return `${minutes}:${String(remainder).padStart(2, '0')}`;
}

export function formatSize(bytes: number | null): string {
  if (bytes === null || !Number.isFinite(bytes)) return '—';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** Body for creating or updating a piece. Only sent keys are applied on PATCH. */
export interface PieceInput {
  title?: string;
  composer_id?: number | null;
  opus?: string | null;
  difficulty?: string | null;
  key?: string | null;
  started_on?: string | null;
  status?: 'active' | 'completed' | 'paused';
  description?: string | null;
}

export interface JournalInput {
  entry_date?: string;
  content?: string;
  practice_minutes?: number | null;
}

export interface DeleteResult {
  deleted: boolean;
  cascaded: Record<string, number>;
}

/** Minutes as a human would say them: 0.4 -> "0.4 min", 90 -> "1 h 30". */
export function formatMinutes(minutes: number): string {
  if (!Number.isFinite(minutes) || minutes <= 0) return '0 min';
  if (minutes < 60) return `${minutes < 10 ? minutes.toFixed(1) : Math.round(minutes)} min`;
  const hours = Math.floor(minutes / 60);
  const rest = Math.round(minutes % 60);
  return rest === 0 ? `${hours} h` : `${hours} h ${rest} min`;
}

/** Seconds as a practice-log duration: 95 -> "1:35", 3800 -> "1:03:20". */
export function formatClock(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const rest = total % 60;
  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, '0')}:${String(rest).padStart(2, '0')}`;
  }
  return `${minutes}:${String(rest).padStart(2, '0')}`;
}
