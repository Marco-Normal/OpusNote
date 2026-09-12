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
export type AppView = 'practice' | 'calibrate' | 'stats';

export const NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'] as const;

export function midiToName(pitch: number): string {
  return `${NOTE_NAMES[((pitch % 12) + 12) % 12]}${Math.floor(pitch / 12) - 1}`;
}
