/**
 * Typed client for the trainer API.
 *
 * The client never generates music or scores a performance itself — every
 * musical judgement comes from the backend. That is what lets the generator and
 * the scorer be replaced without touching the browser code.
 */

import type { Exercise, PlayedNote, PracticeMode, Profile, ScoreResult, SkillInfo, Stats } from './types';

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

  if (!response.ok) {
    let detail: unknown;
    try {
      detail = await response.json();
    } catch {
      detail = await response.text();
    }
    throw new ApiError(`Request to ${path} failed (${response.status})`, response.status, detail);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  health: () => request<{ status: string; database: string; exercises: number; performances: number }>('/health'),

  profile: () => request<Profile>('/profile'),

  resetProfile: () => request<Profile>('/profile/reset', { method: 'POST' }),

  skills: () => request<SkillInfo[]>('/skills'),

  nextExercise: (options: { skill?: string; bars?: number } = {}) => {
    const params = new URLSearchParams();
    if (options.skill) params.set('skill', options.skill);
    if (options.bars) params.set('bars', String(options.bars));
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
};
