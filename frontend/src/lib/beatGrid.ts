/**
 * When every click sounds, and how loud.
 *
 * This is the metronome's arithmetic with the Web Audio scheduling taken out of it, in a module
 * that imports nothing. It is here because the arithmetic is what broke and it could not be
 * tested where it was: `metronome.ts` imports Tone at module scope, so nothing in it can be
 * loaded by `node --test`, and the click grid is the part with a recorded defect behind it —
 * the metronome was handed seconds-per-*quarter* and treated it as seconds-per-*beat*, which
 * coincides only when the beat happens to be a quarter. So 6/8, 9/8, 12/8, 2/2 and 3/8 all
 * clicked at the wrong rate, counted in wrongly, and in 12/8 ended the run a quarter of the way
 * early, silently truncating the performance.
 *
 * The invariant that defect violated, and that `beatGrid.test.ts` now pins, is that **a bar takes
 * as long as its notation says**: the beats of a bar, each multiplied by its own unit and by
 * seconds-per-quarter, must sum to the bar's length in quarters. It holds for any division of a
 * bar into beats, which is exactly why it catches a wrong unit and a missing unit alike.
 */

/** Bar lengths (in notated beats) for the exercise itself, one per bar. */
export interface MetronomePlan {
  barsBeats: number[];
  /**
   * The beat unit per bar, in quarter lengths: 1 for a quarter-note beat, 1.5
   * for the dotted-quarter beat of 6/8, 2 for cut time.
   *
   * This is what makes the metronome correct in compound meter. A beat is not
   * a quarter note, so a single "seconds per beat" derived from the tempo is
   * only right when the meter's beat happens to be a quarter.
   */
  barBeatUnits: number[];
  /** Seconds per quarter note, which is what a tempo marking actually means. */
  secondsPerQuarter: number;
  /** How many beats of count-in to play before beat 1. */
  countInBeats: number;
  /**
   * Click volume, 0..127.
   *
   * On the same scale as a MIDI velocity because the app already has one, and because
   * "60 is quieter than 96" needs no explanation. Absent means the historical default.
   */
  clickVolume?: number;
}

/** One click, with its offset in seconds from the first count-in click. */
export interface ScheduledClick {
  at: number;
  accent: boolean;
  bar: number;
  beat: number;
  inCountIn: boolean;
}

export interface Schedule {
  clicks: ScheduledClick[];
  /** Seconds from the first count-in click to the exercise's beat 1. */
  downbeatSeconds: number;
  /** Seconds from the first count-in click to the end of the last bar. */
  scheduledSeconds: number;
}

/** The default click volume, where 96/127 is a comfortable practice click. */
export const DEFAULT_CLICK_VOLUME = 96;

/**
 * A 0..127 controller value as the decibels Tone expects.
 *
 * 127 maps to -6 dB rather than 0: a metronome that can clip is not a metronome. The
 * curve is the square of the fraction, which is approximately how loudness is heard.
 */
export function toneDbFor(value: number): number {
  const fraction = Math.max(0, Math.min(127, value)) / 127;
  return fraction <= 0 ? -Infinity : -6 + 20 * Math.log10(fraction * fraction);
}

/**
 * Lay out every click up front, in seconds from the first count-in click.
 *
 * Precomputing removes the previous assumption that all beats last the same
 * amount of time, which is false for compound and mixed meters.
 *
 * The count-in follows the **first bar's** meter rather than assuming 4/4, because a count-in
 * that does not match what follows is worse than none: it sets a tempo the player then has to
 * unlearn at the downbeat.
 */
export function buildSchedule(plan: MetronomePlan): Schedule {
  const beatsInFirstBar = plan.barsBeats[0] ?? 4;
  const countInUnit = plan.barBeatUnits[0] ?? 1;
  const clicks: ScheduledClick[] = [];
  let elapsed = 0;

  for (let index = 0; index < plan.countInBeats; index += 1) {
    clicks.push({
      at: elapsed,
      accent: index % beatsInFirstBar === 0,
      bar: 0,
      beat: index + 1,
      inCountIn: true,
    });
    elapsed += countInUnit * plan.secondsPerQuarter;
  }
  const downbeatSeconds = elapsed;

  plan.barsBeats.forEach((beats, barIndex) => {
    const unit = plan.barBeatUnits[barIndex] ?? 1;
    for (let beat = 0; beat < beats; beat += 1) {
      clicks.push({
        at: elapsed,
        accent: beat === 0,
        bar: barIndex + 1,
        beat: beat + 1,
        inCountIn: false,
      });
      elapsed += unit * plan.secondsPerQuarter;
    }
  });

  return { clicks, downbeatSeconds, scheduledSeconds: elapsed };
}
