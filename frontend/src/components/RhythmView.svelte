<script lang="ts">
  /**
   * The shape of practice over time.
   *
   * The question this view answers is not "am I improving" (the ratings own that) but "where
   * did the time go": which weeks grew or shrank, whether the change was a shorter first
   * sitting or a lost second one, which weekdays carry the habit, and what the segment
   * measurements say about how the minutes were spent.
   *
   * The weekly chart is hand-drawn rather than a chart component because it is *stacked*:
   * two quantities per week that must read as one bar. A row of horizontal bars would show
   * the totals and lose the split, which is the whole point of the split.
   */
  import { api } from '../lib/api';
  import type { PracticePortrait, RhythmSummary } from '../lib/types';
  import BarChart from './BarChart.svelte';

  const WINDOWS = [
    { days: 28, label: '4 weeks' },
    { days: 90, label: '3 months' },
    { days: 365, label: '1 year' },
  ];

  const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  const NOTE_NAMES = ['C', 'C♯', 'D', 'E♭', 'E', 'F', 'F♯', 'G', 'A♭', 'A', 'B♭', 'B'];

  let days = $state(90);
  let data = $state<RhythmSummary | null>(null);
  let loading = $state(false);
  let error = $state<string | null>(null);

  // The portrait is a pass over every note in the window, so it is its own request and it
  // arrives after the tiles: the shape of the weeks must not wait for a million notes.
  let portrait = $state<PracticePortrait | null>(null);
  let portraitBusy = $state(false);
  let portraitError = $state<string | null>(null);

  async function load(): Promise<void> {
    loading = true;
    error = null;
    try {
      data = await api.practice.rhythm(days);
    } catch (cause) {
      error = cause instanceof Error ? cause.message : String(cause);
    } finally {
      loading = false;
    }
  }

  async function loadPortrait(): Promise<void> {
    portraitBusy = true;
    portraitError = null;
    try {
      portrait = await api.practice.portrait(days);
    } catch (cause) {
      portraitError = cause instanceof Error ? cause.message : String(cause);
    } finally {
      portraitBusy = false;
    }
  }

  // Runs on mount and whenever the window changes; `days` is read so it is tracked.
  $effect(() => {
    void days;
    void load();
  });

  $effect(() => {
    void days;
    void loadPortrait();
  });

  const weeks = $derived(data?.weeks ?? []);
  const peak = $derived(weeks.reduce((best, week) => Math.max(best, week.minutes), 0));

  /** True for a bucket the window only partly covers — its bar is not comparable. */
  function partial(weekStart: string): boolean {
    if (!data || !data.window_start) return false;
    const start = Date.parse(`${weekStart}T00:00:00`);
    const from = Date.parse(`${data.window_start}T00:00:00`);
    const to = Date.parse(`${data.window_end}T00:00:00`);
    // Six days past its Monday is the week's Sunday.
    return start < from || start + 6 * 86_400_000 > to;
  }

  function weekLabel(iso: string): string {
    const date = new Date(`${iso}T00:00:00`);
    return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  }

  /** Label every n-th bar so a year's worth does not overlap itself. */
  const labelEvery = $derived(weeks.length > 20 ? 4 : weeks.length > 10 ? 2 : 1);

  const firstTotal = $derived(weeks.reduce((sum, week) => sum + week.first_minutes, 0));
  const extraTotal = $derived(weeks.reduce((sum, week) => sum + week.extra_minutes, 0));

  const adherence = $derived(
    data && data.elapsed_days > 0 ? (data.practised_days / data.elapsed_days) * 100 : 0,
  );

  const weekdayItems = $derived(
    (data?.weekdays ?? []).map((row) => ({
      label: WEEKDAYS[row.weekday],
      value: row.minutes,
      hint: row.practised_days === 1 ? '1 day' : `${row.practised_days} days`,
    })),
  );

  const sessionItems = $derived(
    (data?.session_counts ?? []).map((row) => ({
      label: row.sessions === 4 ? '4 or more' : row.sessions === 1 ? '1 session' : `${row.sessions} sessions`,
      value: row.days,
      hint: row.days === 1 ? '1 day' : `${row.days} days`,
    })),
  );

  function fmt(value: number | null, unit = ''): string {
    if (value === null || value === undefined) return '—';
    return `${value}${unit}`;
  }

  function signed(value: number | null | undefined): string {
    if (value === null || value === undefined) return '—';
    return `${value > 0 ? '+' : ''}${value.toFixed(2)}`;
  }

  /** Scientific pitch: MIDI 60 is C4, which is also how the library's ranges read. */
  function noteName(midi: number | null): string {
    if (midi === null || midi === undefined) return '—';
    // The centre of gravity is a mean, so it is not on a key. Naming it rounds to the
    // nearest one; a fractional index would read as `undefined`.
    const key = Math.round(midi);
    return `${NOTE_NAMES[key % 12]}${Math.floor(key / 12) - 1}`;
  }

  const hourPeak = $derived(
    (data?.hours ?? []).reduce((best, row) => Math.max(best, row.minutes), 0),
  );

  /** The hours that actually hold practice, for the sentence under the chart. */
  const practisedHours = $derived((data?.hours ?? []).filter((row) => row.minutes > 0));

  const morningHours = $derived(practisedHours.filter((row) => row.hour < 12).length);
  const earliestHour = $derived(practisedHours.length > 0 ? practisedHours[0].hour : null);
  const latestHour = $derived(
    practisedHours.length > 0 ? practisedHours[practisedHours.length - 1].hour : null,
  );

  const correlation = $derived(
    Object.fromEntries((data?.autocorrelations ?? []).map((row) => [row.lag, row.r])),
  );

  const strongestLag = $derived(
    (data?.autocorrelations ?? []).reduce(
      (best, row) => (row.r !== null && (best.r === null || Math.abs(row.r) > Math.abs(best.r)) ? row : best),
      { lag: 0, r: null as number | null, pairs: 0 },
    ),
  );

  const octaveItems = $derived(
    (portrait?.keyboard.octaves ?? []).map((row) => ({
      label: `C${row.octave}`,
      value: row.notes,
      hint: row.notes === 1 ? '1 note' : `${row.notes} notes`,
    })),
  );

  const pitchClassItems = $derived(
    (portrait?.keyboard.pitch_classes ?? [])
      .filter((row) => row.notes > 0)
      .slice()
      .sort((a, b) => b.notes - a.notes)
      .map((row) => ({
        label: NOTE_NAMES[row.pitch_class],
        value: row.notes,
        hint: portrait
          ? `${((row.notes / Math.max(portrait.notes, 1)) * 100).toFixed(1)}% of the notes`
          : '',
      })),
  );

  const spanBaseline = $derived(portrait?.velocity_spans[0]?.mean_velocity ?? null);

  const spanItems = $derived(
    (portrait?.velocity_spans ?? []).map((row) => ({
      label: ['First quarter', 'Second quarter', 'Third quarter', 'Last quarter'][row.span],
      value: row.mean_velocity ?? 0,
      hint: row.notes === 0 ? 'no notes' : `${row.notes} notes`,
    })),
  );

  const travelMetres = $derived(portrait ? Math.round(portrait.travel.metres) : 0);
</script>

<section class="card panel">
  <div class="spread wrap">
    <div>
      <h3>Practice rhythm</h3>
      <p class="muted small">
        Where the time went — by week, by weekday, and by how it was played. Minutes are the
        stored length of each sitting, added up; they are not wall-clock time between the
        first and last note.
      </p>
    </div>
    <label class="row pick">
      <span class="muted small">Window</span>
      <select bind:value={days} data-rhythm-window>
        {#each WINDOWS as option (option.days)}
          <option value={option.days}>{option.label}</option>
        {/each}
      </select>
    </label>
  </div>

  {#if error}
    <p class="error">{error}</p>
  {/if}

  {#if !data}
    <p class="muted small">{loading ? 'Reading the log…' : 'Nothing loaded.'}</p>
  {:else if data.sittings === 0}
    <p class="muted small" data-rhythm="empty">
      No practice in the last {data.days} days. Play a few notes and this fills in.
    </p>
  {:else}
    <div class="tiles" data-rhythm="ready" data-weeks={weeks.length} data-rhythm-days={data.days}>
      <div class="tile">
        <span class="k">Practised days</span>
        <span class="v" data-rhythm-adherence
          >{data.practised_days}<small> of {data.elapsed_days} ({Math.round(adherence)}%)</small></span
        >
      </div>
      <div class="tile">
        <span class="k">Minutes</span>
        <span class="v">{data.minutes}<small> total</small></span>
      </div>
      <div class="tile">
        <span class="k">Median sitting</span>
        <span class="v">{fmt(data.median_session_minutes)}<small> min</small></span>
      </div>
      <div class="tile">
        <span class="k">Longest</span>
        <span class="v">{data.longest_session_minutes}<small> min</small></span>
      </div>
      <div class="tile">
        <span class="k">Sittings / day</span>
        <span class="v">{fmt(data.sessions_per_practised_day)}</span>
      </div>
    </div>

    <h4>Week by week</h4>
    <div class="chart-wrap">
      <div class="legend">
        <span><i class="swatch first"></i> first sitting of the day</span>
        <span><i class="swatch extra"></i> later sittings</span>
      </div>
      <div class="chart" aria-hidden="true">
        {#each weeks as week, index (week.week_start)}
          <div
            class="week"
            class:partial={partial(week.week_start)}
            data-week={week.week_start}
            data-minutes={week.minutes}
            title={`Week of ${week.week_start}: ${week.minutes} min over ${week.practised_days} day(s), ${week.sittings} sitting(s)`}
          >
            <div class="bar" style="height: {peak > 0 ? Math.max(1, (week.minutes / peak) * 100) : 0}%">
              <span
                class="seg first"
                style="height: {week.minutes > 0 ? (week.first_minutes / week.minutes) * 100 : 0}%"
              ></span>
              <span
                class="seg extra"
                style="height: {week.minutes > 0 ? (week.extra_minutes / week.minutes) * 100 : 0}%"
              ></span>
            </div>
            <span class="tick muted">
              {#if week.minutes > 0 && weeks.length > 0}
                {#if index % labelEvery === 0}{weekLabel(week.week_start)}{/if}
              {/if}
            </span>
          </div>
        {/each}
      </div>
      <p class="muted small">
        {firstTotal} minutes came from the first sitting of a day and {extraTotal} from every
        later one. A total that falls while the first-sitting share holds is a lost second
        session, not a shorter habit. Bars with a dashed outline are weeks the window only
        partly covers.
      </p>
    </div>

    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Week</th>
            <th>Days</th>
            <th>Sittings</th>
            <th>Minutes</th>
            <th>First</th>
            <th>Later</th>
            <th>Longest</th>
          </tr>
        </thead>
        <tbody>
          {#each weeks as week (week.week_start)}
            <tr data-week-row={week.week_start}>
              <td class="mono">{weekLabel(week.week_start)}{partial(week.week_start) ? ' ◇' : ''}</td>
              <td class="mono">{week.practised_days}</td>
              <td class="mono">{week.sittings}</td>
              <td class="mono">{week.minutes}</td>
              <td class="mono">{week.first_minutes}</td>
              <td class="mono">{week.extra_minutes}</td>
              <td class="mono">{week.longest_minutes}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</section>

{#if data && data.sittings > 0}
  <div class="grid">
    <section class="card panel">
      <h3>Which weekday carries the habit</h3>
      <BarChart items={weekdayItems} empty="No practice in this window." />
      <p class="muted small">
        Total minutes per weekday over the window, so a busy Monday and a rare but long
        Sunday both show up. The hint under each bar is how many days carried practice.
      </p>
    </section>

    <section class="card panel">
      <h3>How many sittings a day</h3>
      <BarChart items={sessionItems} unit=" day(s)" empty="No practice in this window." />
      <p class="muted small">
        A "sitting" ends when the piano has been quiet long enough for the app to call it
        finished, so two sittings in one day means a real break, not a pause between pieces.
      </p>
    </section>
  </div>

  <section class="card panel" data-rhythm-hours={data.hours.length}>
    <h3>When in the day</h3>
    <div class="hour-chart" aria-hidden="true">
      {#each data.hours as row (row.hour)}
        <div
          class="hour"
          class:empty={row.minutes === 0}
          data-hour={row.hour}
          data-hour-minutes={row.minutes}
          title={`${String(row.hour).padStart(2, '0')}:00 — ${row.minutes} min in ${row.sittings} sitting(s)`}
        >
          <div
            class="bar"
            style="height: {hourPeak > 0 ? Math.max(1, (row.minutes / hourPeak) * 100) : 0}%"
          ></div>
          <span class="tick muted">{row.hour % 3 === 0 ? row.hour : ''}</span>
        </div>
      {/each}
    </div>
    <p class="muted small">
      On the player's own clock, not the file's — a 21:00 evening stays at 21:00 for a reader
      in another timezone. A sitting that crosses an hour is split at it, so these bars add up
      to the window's minutes.
      {#if earliestHour !== null && latestHour !== null}
        Every minute in this window falls between {String(earliestHour).padStart(2, '0')}:00 and
        {String(latestHour).padStart(2, '0')}:00, and {morningHours === 0
          ? 'none of it before noon'
          : `${morningHours} hour(s) of it before noon`}.
      {/if}
    </p>
    <div class="tiles">
      {#each [1, 7, 14] as lag (lag)}
        <div class="tile">
          <span class="k">{lag === 1 ? '1 day' : `${lag} days`}</span>
          <span class="v" data-rhythm-lag={lag}>{signed(correlation[lag])}</span>
        </div>
      {/each}
      <div class="tile">
        <span class="k">Days in window</span>
        <span class="v">{data.elapsed_days}</span>
      </div>
    </div>
    <p class="muted small">
      These three numbers are the daily minutes correlated with themselves one, seven and
      fourteen days earlier, with empty days kept as zeros. A positive value means a long day
      tends to follow another long day at that distance; negative means the opposite. It is a
      description of the habit, not a claim about why.
      {#if strongestLag.r !== null}
        The strongest of the three is {strongestLag.lag}
        {strongestLag.lag === 1 ? 'day' : 'days'} at {signed(strongestLag.r)}.
      {/if}
    </p>
  </section>

  <section class="card panel" data-rhythm-technique={data.technique.segments}>
    <h3>How it was played</h3>
    {#if data.technique.segments === 0}
      <p class="muted small">
        No segment measurements in this window yet. They are computed when a sitting is
        closed, so the most recent practice may still be in progress.
      </p>
    {:else}
      <div class="tiles">
        <div class="tile">
          <span class="k">Note rate</span>
          <span class="v">{fmt(data.technique.mean_tempo)}<small> /min</small></span>
        </div>
        <div class="tile">
          <span class="k">Touch</span>
          <span class="v">{fmt(data.technique.mean_velocity)}<small> velocity</small></span>
        </div>
        <div class="tile">
          <span class="k">Left / right</span>
          <span class="v"
            >{fmt(data.technique.mean_velocity_low)}<small> / {fmt(data.technique.mean_velocity_high)}</small></span
          >
        </div>
        <div class="tile">
          <span class="k">Restarts</span>
          <span class="v">{fmt(data.technique.restarts_per_minute)}<small> /min</small></span>
        </div>
        <div class="tile">
          <span class="k">Pedal down</span>
          <span class="v"
            >{data.technique.pedal_down_ratio === null
              ? '—'
              : `${Math.round(data.technique.pedal_down_ratio * 100)}%`}</span
          >
        </div>
        <div class="tile">
          <span class="k">Blurs</span>
          <span class="v">{fmt(data.technique.blurs_per_minute)}<small> /min</small></span>
        </div>
      </div>
      <p class="muted small">
        Averages of the {data.technique.segments} measured segments
        ({data.technique.measured_minutes} min), so one long rambling section does not
        outweigh a short hard one. "Note rate" is notes per minute from note onsets, not a
        metronome tempo — sixteenths read about four times their marking. "Left / right"
        splits velocity at middle C, which is the app's hand proxy. Pedal figures use only
        the {data.technique.pedal_segments} segment(s) that carried pedal data; a sitting
        imported without a pedal stream is not the same as one played without the pedal.
      </p>
    {/if}
  </section>

  {#if portraitError}
    <section class="card panel" data-portrait="error">
      <h3>The portrait</h3>
      <p class="error">{portraitError}</p>
    </section>
  {:else if !portrait}
    <section class="card panel" data-portrait="loading">
      <h3>The portrait</h3>
      <p class="muted small">
        {portraitBusy
          ? 'Reading every note in the window — this one takes a moment.'
          : 'Nothing loaded.'}
      </p>
    </section>
  {:else}
    <section
      class="card panel"
      data-portrait="ready"
      data-portrait-notes={portrait.notes}
      data-portrait-keys={portrait.keyboard.distinct_keys}
    >
      <h3>The keys you used</h3>
      {#if portrait.notes === 0}
        <p class="muted small">No notes in this window.</p>
      {:else}
        <div class="tiles">
          <div class="tile">
            <span class="k">Notes</span>
            <span class="v">{portrait.notes.toLocaleString()}</span>
          </div>
          <div class="tile">
            <span class="k">Keys used</span>
            <span class="v">{portrait.keyboard.distinct_keys}<small> of 88</small></span>
          </div>
          <div class="tile">
            <span class="k">Range</span>
            <span class="v"
              >{noteName(portrait.keyboard.lowest)}<small>–{noteName(portrait.keyboard.highest)}</small></span
            >
          </div>
          <div class="tile">
            <span class="k">Centre</span>
            <span class="v">{noteName(portrait.keyboard.mean_pitch)}</span>
          </div>
          <div class="tile">
            <span class="k">Travel</span>
            <span class="v"
              >{travelMetres >= 1000 ? (travelMetres / 1000).toFixed(1) : travelMetres}<small
                >{travelMetres >= 1000 ? ' km' : ' m'}</small
              ></span
            >
          </div>
          <div class="tile">
            <span class="k">Attacks</span>
            <span class="v">{portrait.texture.attacks.toLocaleString()}</span>
          </div>
          <div class="tile">
            <span class="k">Notes / attack</span>
            <span class="v">{fmt(portrait.texture.notes_per_attack)}</span>
          </div>
          <div class="tile">
            <span class="k">Chords</span>
            <span class="v"
              >{portrait.texture.chord_share === null
                ? '—'
                : `${Math.round(portrait.texture.chord_share * 100)}%`}</span
            >
          </div>
        </div>

        <div class="grid inner">
          <div>
            <h4>Which octaves</h4>
            <BarChart items={octaveItems} unit=" notes" empty="No notes in this window." />
          </div>
          <div>
            <h4>Which notes</h4>
            <BarChart items={pitchClassItems} unit=" notes" empty="No notes in this window." />
          </div>
        </div>
      {/if}

      <h3>How it felt</h3>
      <div class="tiles">
        <div class="tile">
          <span class="k">Touch</span>
          <span class="v">{fmt(portrait.touch.mean_velocity)}<small> velocity</small></span>
        </div>
        <div class="tile">
          <span class="k">Palette</span>
          <span class="v">{portrait.touch.distinct_velocities}<small> of 127</small></span>
        </div>
        <div class="tile">
          <span class="k">Spread</span>
          <span class="v">{fmt(portrait.touch.entropy_bits)}<small> bits</small></span>
        </div>
        <div class="tile">
          <span class="k">Dynamic range</span>
          <span class="v">{fmt(portrait.touch.dynamic_range_db)}<small> dB*</small></span>
        </div>
        <div class="tile">
          <span class="k">Regularity</span>
          <span class="v">{fmt(portrait.timing.cv)}<small> CV</small></span>
        </div>
        <div class="tile">
          <span class="k">Attacks / min</span>
          <span class="v">{fmt(portrait.texture.attacks_per_minute)}</span>
        </div>
      </div>

      {#if spanItems.length > 0}
        <h4>Loudness across the window</h4>
        <div class="tiles">
          {#each spanItems as row (row.label)}
            <div class="tile">
              <span class="k">{row.label}</span>
              <span class="v"
                >{row.value === 0 ? '—' : row.value.toFixed(1)}<small
                  >{row.value === 0
                    ? ''
                    : spanBaseline !== null && row.label !== 'First quarter'
                      ? ` ${signed(row.value - spanBaseline)}`
                      : ' velocity'}</small
                ></span
              >
            </div>
          {/each}
        </div>
        <p class="muted small">
          Mean touch in each quarter of the practised span, with the change from the first
          quarter beside it. Velocity is a MIDI number out of 127, not a sound-pressure level.
        </p>
      {/if}

      <p class="muted small">
        Descriptive, not a mark. <em>Touch</em> is MIDI velocity, and the *dB figure is a
        velocity ratio (20 log₁₀ max/min), not a sound-pressure level — it cannot be compared
        across instruments or rooms. <em>Notes per attack</em> groups onsets within 40 ms, so a
        rolled chord is one attack; above 1 means something was sounding together.
        <em>Regularity</em> is the coefficient of variation of the gaps between attacks inside
        phrases (2 s or less), so a pause between thoughts is not counted as uneven playing.
        <em>Travel</em> converts semitones at 17 cm per octave — an intuition, not a
        measurement of the hands.
      </p>
    </section>
  {/if}
{/if}

<style>
  .panel {
    padding: 0.9rem 1rem;
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
  }

  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(19rem, 1fr));
    gap: 0.9rem;
    margin-top: 0.9rem;
  }

  .tiles {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(8.5rem, 1fr));
    gap: 0.5rem;
  }

  .tile {
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
    padding: 0.5rem 0.65rem;
    border-radius: var(--radius);
    border: 1px solid var(--line);
    background: var(--surface-2);
  }

  .tile .k {
    font-size: 0.75rem;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  .tile .v {
    font-size: 1.3rem;
    font-weight: 600;
  }

  .tile .v small {
    font-size: 0.72rem;
    color: var(--muted);
    font-weight: 400;
  }

  .hour-chart {
    display: flex;
    align-items: flex-end;
    gap: 1px;
    height: 110px;
    padding-top: 0.3rem;
    border-bottom: 1px solid var(--line);
  }

  .hour {
    flex: 1 1 0;
    min-width: 0;
    height: 100%;
    display: flex;
    flex-direction: column;
    justify-content: flex-end;
    gap: 0.2rem;
  }

  .hour .bar {
    background: var(--accent);
    border-radius: 2px 2px 0 0;
    min-height: 0;
  }

  .hour.empty .bar {
    background: var(--track);
  }

  .hour .tick {
    font-size: 0.65rem;
    text-align: center;
    overflow: hidden;
    white-space: nowrap;
  }

  .grid.inner {
    grid-template-columns: repeat(auto-fit, minmax(16rem, 1fr));
    margin-top: 0.2rem;
  }

  .chart-wrap {
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
  }

  .legend {
    display: flex;
    gap: 1rem;
    font-size: 0.75rem;
    color: var(--muted);
  }

  .swatch {
    display: inline-block;
    width: 0.7rem;
    height: 0.7rem;
    border-radius: 2px;
    margin-right: 0.3rem;
    vertical-align: -1px;
  }

  .swatch.first {
    background: var(--accent);
  }

  .swatch.extra {
    background: var(--accent-soft);
    border: 1px solid var(--accent);
  }

  .chart {
    display: flex;
    align-items: flex-end;
    gap: 2px;
    height: 150px;
    padding-top: 0.3rem;
    border-bottom: 1px solid var(--line);
    overflow: hidden;
  }

  .week {
    flex: 1 1 0;
    min-width: 0;
    height: 100%;
    display: flex;
    flex-direction: column;
    align-items: stretch;
    justify-content: flex-end;
    gap: 0.25rem;
  }

  .bar {
    display: flex;
    flex-direction: column-reverse;
    min-height: 0;
    border-radius: 2px 2px 0 0;
    overflow: hidden;
    background: var(--surface-2);
  }

  .week.partial .bar {
    outline: 1px dashed var(--line);
    outline-offset: 1px;
  }

  .seg {
    display: block;
    width: 100%;
  }

  .seg.first {
    background: var(--accent);
  }

  .seg.extra {
    background: var(--accent-soft);
  }

  .tick {
    font-size: 0.65rem;
    text-align: center;
    white-space: nowrap;
    overflow: visible;
    height: 1rem;
  }

  .pick {
    gap: 0.35rem;
  }

  .error {
    color: var(--bad);
  }
</style>
