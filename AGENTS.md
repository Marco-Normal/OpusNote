# AGENTS.md — read this first

The entry point for anyone (human or agent) working in this repository. **It points; it does not
restate.** Every fact below already has an owner, and the owner is the link. If a line here
disagrees with its owner, the owner is right and this file is a bug — fix it, do not update the
fact here.

Opus Note is an adaptive sight-reading coach and practice journal for a real acoustic piano:
Python 3.11 / FastAPI / SQLite / music21 on the server, Svelte 5 / TypeScript / Vite in the
browser. [`README.md`](README.md) is the front page. [`docs/FEATURES.md`](docs/FEATURES.md) is
what it does; [`docs/ENGINEERING.md`](docs/ENGINEERING.md) is how it is built.

## Verify before you claim anything

| Command | Cost | Use it |
| --- | --- | --- |
| [`./check.sh --fast`](check.sh) | budget 180 s | After **every** edit. Tests, docs gates, typecheck, build |
| `./check.sh --full` | ~10 min | Before handing work over: adds browser scenarios, coverage, mutation |
| `./check.sh --falsify <filter>` | up to ~40 min | When you add or touch an assertion. See below |
| `cd frontend && npm test` | ~2 s | One frontend unit file while iterating |
| `backend/.venv/bin/python backend/tools/check_docs.py` | <1 s | Documentation only |

**No assertion is trusted until it has been seen to fail.** A test that cannot fail is a green
light over nothing, and this repository has found several. If you add a test, add a break script
for it under [`backend/tools/falsifications/`](backend/tools/falsifications) and prove it catches
its own break. The rule and the tiers are owned by
[`docs/TEST-STRATEGY.md`](docs/TEST-STRATEGY.md) §8.

Two traps of the falsify harness, both of which have bitten here: it **refuses to start on a dirty
tree** (it restores with `git checkout`), so commit first; and it **rebuilds
`frontend/dist` itself** because the bundle is gitignored and a stale one silently falsifies the
wrong answer.

## Where the truth lives

Where a *behaviour* question sends you: the document in the **owner** column.

| If you are asking about… | Owner |
| --- | --- |
| How a feature behaves for the player | [`docs/FEATURES.md`](docs/FEATURES.md) |
| Architecture, the API contract, difficulty model, adaptive engine, scorer, timing, every tunable, known limitations | [`docs/ENGINEERING.md`](docs/ENGINEERING.md) |
| What a change's cost may scale with, and how to measure it | [`docs/PERFORMANCE.md`](docs/PERFORMANCE.md) |
| Running it on the piano machine, the LAN boundary, backup, moving machines | [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) and [`deploy/README.md`](deploy/README.md) — read as a pair |
| What the tests must cover, which tier a change owes | [`docs/TEST-STRATEGY.md`](docs/TEST-STRATEGY.md) |
| The local-only real-data fixture, and the trap it holds | [`docs/TEST-DATA.md`](docs/TEST-DATA.md) |
| Which document a change obliges you to update | [`docs/ECOSYSTEM.md`](docs/ECOSYSTEM.md) § *The standing rule for documentation* |
| Licence notices | [`THIRD-PARTY.md`](THIRD-PARTY.md) |

Where a *code* question sends you: the file in the **owner** column. This is the map an agent
wants and the `README`'s directory layout does not give — the directory is not the fact.

| If you are changing… | Canonical owner |
| --- | --- |
| The difficulty model: what a level *means* | [`backend/app/skills_data.py`](backend/app/skills_data.py) — single source of truth, validated at import |
| Which exercise comes next (Elo, selection, pins) | [`backend/app/adaptive/selector.py`](backend/app/adaptive/selector.py), [`backend/app/adaptive/elo.py`](backend/app/adaptive/elo.py) |
| Accepting a performance, persisting it, rating it | [`backend/app/services.py`](backend/app/services.py) |
| Score generation | [`backend/app/music/generator.py`](backend/app/music/generator.py) plus its siblings: [`bass_patterns.py`](backend/app/music/bass_patterns.py), [`harmony.py`](backend/app/music/harmony.py), [`melody.py`](backend/app/music/melody.py), [`tonality.py`](backend/app/music/tonality.py) |
| The expected-note timeline, or which hand a note is | [`backend/app/music/expected.py`](backend/app/music/expected.py) — **the authority**; the browser mirrors its rule rather than re-deciding it |
| Scoring: pitch, rhythm, continuity | [`backend/app/scoring/engine.py`](backend/app/scoring/engine.py) |
| Any tunable or its default | [`backend/app/config.py`](backend/app/config.py), documented in [`docs/ENGINEERING.md`](docs/ENGINEERING.md) §8 |
| A table, a column, a migration | [`backend/app/db.py`](backend/app/db.py) for the core, and the owning domain's `schema.py`; then `docs/ECOSYSTEM.md`'s trigger table |
| Ingesting notes, sittings, closing a sitting | [`backend/app/practice/store.py`](backend/app/practice/store.py) |
| Where a segment boundary falls | [`backend/app/practice/segment.py`](backend/app/practice/segment.py) |
| Grouping attempts into passages | [`backend/app/practice/passages.py`](backend/app/practice/passages.py) |
| Recognising which piece was played | [`backend/app/practice/similarity.py`](backend/app/practice/similarity.py) and [`shingles.py`](backend/app/practice/shingles.py) for the content match; the writing of a guess lives in [`store.py`](backend/app/practice/store.py) (`autotag_sitting`) |
| Per-segment measurements, the pedal, blur | [`backend/app/practice/metrics.py`](backend/app/practice/metrics.py), [`backend/app/practice/pedal.py`](backend/app/practice/pedal.py) |
| The library: pieces, journal, passages, media, takes | [`backend/app/repertoire/`](backend/app/repertoire) |
| Workouts | [`backend/app/workout/`](backend/app/workout) |
| The repertoire → sight-reading seam | [`backend/app/bridge.py`](backend/app/bridge.py) — the only module that knows both domains |
| The HTTP contract | [`backend/app/main.py`](backend/app/main.py) and each domain's `api.py`; documented in `docs/ENGINEERING.md` §2 |
| MIDI input, note/CC decoding, capture | [`frontend/src/lib/midi.ts`](frontend/src/lib/midi.ts), [`frontend/src/lib/capture.ts`](frontend/src/lib/capture.ts) |
| The attempt being recorded and scored | [`frontend/src/lib/scoredAttempt.ts`](frontend/src/lib/scoredAttempt.ts) |
| The count-in, the click grid, tempo arithmetic | [`frontend/src/lib/countIn.ts`](frontend/src/lib/countIn.ts), [`frontend/src/lib/beatGrid.ts`](frontend/src/lib/beatGrid.ts), [`frontend/src/lib/metronome.ts`](frontend/src/lib/metronome.ts) |
| Engraving, zoom, note colouring | [`frontend/src/lib/score.ts`](frontend/src/lib/score.ts) — read its header first; OSMD's traps are recorded there |
| Playback, hands, pedals in playback | [`frontend/src/lib/playback.ts`](frontend/src/lib/playback.ts), [`frontend/src/lib/pianoPlayer.ts`](frontend/src/lib/pianoPlayer.ts) |
| Colour, type, shape | [`frontend/src/app.css`](frontend/src/app.css) — the design tokens, single source |
| A view or the shell | [`frontend/src/App.svelte`](frontend/src/App.svelte), [`frontend/src/components/`](frontend/src/components), [`frontend/src/lib/state.svelte.ts`](frontend/src/lib/state.svelte.ts) |

## The traps that cost real time

Not a summary of the docs — the specific things that have silently broken here, each of which a
careful reader still gets wrong. The full reasoning is at the owner.

- **The count-in is not scored.** Capture is anchored at beat 1 on purpose, so a note during the
  count-in arrives with a **negative onset** and is dropped by `scoredAttempt.ts`. Do not "fix" a
  negative onset; it is the boundary working.
- **A tempo marking is quarter notes per minute; a beat is whatever the meter says.** Dotted
  quarter in 6/8, half note in cut time. Conflating them broke the metronome, the count-in and the
  end-of-run timer in every compound meter.
- **A part's identity is not its staff index.** Reading `staffIndex` is right for two hands and for
  a right-hand-alone exercise, and wrong for a left-hand-alone one, which cost every note its
  colour at texture level 2 for as long as that level existed. The authority is `music/expected.py`.
- **OSMD appends on `render()`, and `autoResize` wipes per-note colours.** Re-render means clear
  first; layout is ours. See `frontend/src/lib/score.ts` and `docs/ENGINEERING.md` §7.
- **`frontend/dist` is gitignored**, so `git checkout` cannot restore it. Any browser-measured
  claim about a source edit must rebuild first.
- **The expected-note timeline carries no velocity.** The generator emits dynamic markings at
  articulation levels 7–10 and the scorer ignores them; this is known and documented, not a bug to
  discover twice.
- **`find_reusable_exercise`'s key has had to learn a field five times.** A new pin that is not in
  it serves a stored exercise for the wrong request — silently.
- **The log and the library are different domains with different schemas.** `practice/` never
  imports `repertoire/`; use `bridge.py`.
- **Docs move with the code, in the same commit.** The trigger table is in `ECOSYSTEM.md`, and
  `check_docs.py` runs in `--fast` so a broken link, an unreachable document or a stale phase
  status fails the tier.

## Do not read these to find out how something works

| Path | What it is | Read it only when |
| --- | --- | --- |
| [`AGENT-LOG.md`](AGENT-LOG.md) | Append-only session log, ~267 KB, never edited | You need *why* a specific change was made, or a past defect's evidence |
| [`../.scratch/agent-sessions/`](../.scratch/agent-sessions) | Per-run agent summaries, kept outside the repo on purpose | You want the goal, commits and commands of one agent run rather than one change |
| `docs/PLAN-*.md` | Implementation records for landed phases | You need the reasoning behind a shipped phase |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | **Superseded** by ECOSYSTEM | You want the original slicing reasoning |
| [`docs/INTEGRATION-practice-logger.md`](docs/INTEGRATION-practice-logger.md) | **Superseded** | You want what the two-project integration verified |
| [`docs/archive/`](docs/archive) | Index of the historical material above | You are looking for something old on purpose |

**A landed plan is a record, not a specification.** Every `docs/PLAN-*.md` ends with a closing
`<!-- historical-record -->` banner, and `check_docs.py` refuses any document that carries one
without a `Status:` — so a record always says whether its work landed. The marker counts only as a
closing banner, in the last lines of the file: a document that merely *describes* the convention,
like [`docs/archive/README.md`](docs/archive/README.md), must not thereby claim to be a record
itself. If you are told to implement something and the only source is a landed plan, you are
re-running finished work.

Current behaviour is in `docs/FEATURES.md`. The current phase status is the status line at the top
of `docs/ECOSYSTEM.md`. Nothing else in this repository is the current answer to "how does it work".

## Conventions that are not obvious

- **Tests run as `node --test` on TypeScript directly**, so a `lib/*.ts` module must load under
  Node's strip-only type stripping: no parameter properties, no `enum`, no `namespace`, and a
  relative **value** import needs its `.ts` extension (`import type` is erased and is fine).
- **Pure logic goes in `frontend/src/lib/`, not in the component.** The test runner reaches `lib/`
  and nothing else. `segmentUndo.ts`, `countIn.ts` and `scoredAttempt.ts` are the pattern to copy —
  `scoredAttempt.ts` in particular shows the shape: a small class over the data, a test beside it,
  and a component that only wires events to it.
- **Count work, do not time it, in a test.** A timing assertion passes on a fast laptop with the bug
  present.
- **The scorer's word for a wrong note is `wrong_pitch`, not `wrong`.** Statuses are
  `correct | wrong_pitch | missed`, plus `extra` from the live matcher.
- **One owner per domain, and the API is the contract.** The client makes no musical judgements; if
  the browser needs a score, it asks `/api/score`.
