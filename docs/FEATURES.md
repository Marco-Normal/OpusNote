# Feature reference

Detailed behaviour of Opus Note. The [README](../README.md) is the front page; this document
is the reference for what each feature does and the decisions behind it.

- [1. MIDI input](#1-midi-input)
- [2. Pedal control](#2-pedal-control)
- [3. Two hands and the left-hand library](#3-two-hands-and-the-left-hand-library)
- [4. Exercise length and Focus mode](#4-exercise-length-and-focus-mode)
- [5. The library](#5-the-library)
- [6. Practice log](#6-practice-log)
- [7. Progress](#7-progress)
- [8. Playback](#8-playback)
- [9. Health, backup and export](#9-health-backup-and-export)
- [10. Appearance](#10-appearance)
- [11. Viewing from another machine](#11-viewing-from-another-machine)

---

## 1. MIDI input

The application connects to a class-compliant MIDI keyboard automatically on load, and again
when a keyboard is switched on later, so a machine left running picks it up without
interaction. **Connect MIDI** is required only the first time, to grant the browser MIDI
access.

Selection is by evidence rather than position. On Linux, ALSA always exposes a virtual
`Midi Through Port-0` alongside the real device; it is a valid Web MIDI input that never
carries a note, and selecting by index chooses it roughly half the time. The Setup panel
therefore lists every input with what has actually been heard from it — `17 notes · last 4 s
ago`, or `no notes yet` — and reports which one is in use (`Auto · CASIO USB-MIDI MIDI 1`).

- **Automatic by default.** `Use only this` pins a device when certainty is preferred, and
  the choice survives a reload. `Back to automatic selection` reverses it.
- **Echoes are discarded, not ports ignored.** Every port stays attached, and a note reported
  twice within 30 ms by two different ports is counted once, so a keyboard that splits zones
  across ports loses nothing.
- Development note: use `localhost` rather than `127.0.0.1` for the Vite dev server, since
  that is where it binds and Web MIDI requires a secure context.

## 2. Pedal control

The PX-870 has three pedals. The sostenuto is barely used musically, which makes it the one
viable hands-free switch: one press and release arms take recording, and another stops it.

The damper and the soft pedal are deliberately unbound. Both are *played*, so a press
mid-phrase would end the take being recorded. The damper previously carried a double-tap
gesture that toggled a workout; it was retired for exactly this reason, and workouts are now
declared from the banner instead.

Two invariants govern the gesture:

- It is **inert during a scored attempt**, so a stray pedal cannot disturb a run.
- Nothing is ever bound to a controller message the instrument has not been observed to send.
  The Setup panel reports which controllers the piano has actually sent, because a gesture
  bound to a message the instrument never emits is a feature that silently does not exist.

## 3. Two hands and the left-hand library

From texture level 3 upward, exercises are written on a grand staff and both hands are read
together. The left hand is drawn from a library of **18 named accompaniment figures**:

| Family | Figures |
| --- | --- |
| Sustained | held root, root-and-fifth, block chords |
| Pulse | root-fifth "boom-chick", march bass, waltz bass, stride bass, tenths |
| Broken chord | Alberti bass, compound (6/8) form, ascending broken chords, wide arpeggios, broken octaves |
| Independent | walking bass, free left-hand line, countermelody, canon |

The figure is chosen from the meter and the texture level — a waltz bass never appears in
4/4 — and every figure is unit-tested for exact bar fill, register and diatonicism. The
exercise header names the figure in use.

Figures need harmonic material to outline, so a small diatonic progression engine supplies one
chord per bar (I–V at the beginner end, through vi and ii and inversions later) and always
cadences onto the dominant then the tonic. When both hands play, the melody's downbeats are
anchored to the chord; a solo line is left free because it has nothing to clash with.

## 4. Exercise length and Focus mode

The **Bars** control selects 4, 8, 12 or 16 bars. Length is a preference rather than part of
difficulty, so `difficulty_elo` continues to mean one thing.

The governing rule for sight-reading is that **the music must never scroll during a
performance** — looking away is the failure the application exists to train against. Three
mechanisms enforce it:

- The engraving scales down, to a floor of 55%, until the whole exercise fits.
- While a run is in progress the surrounding chrome collapses, so nothing competes with the
  score for height.
- **Focus** hides the header, device bar and note strip outright, which is the correct choice
  in a small window.

If a length cannot fit even at minimum zoom, the application says so and offers a shorter one
rather than presenting a score that scrolls.

**Count-in and click.** Setup offers a count-in of none, one bar or two bars, and a click
volume beside it. Both are remembered, and the transport reports how many beats the count-in
actually used. The count-in length follows the first bar's meter rather than assuming 4/4.

**Deliberate practice: pinning the difficulty and the hand.** Left alone, the difficulty comes from
the ratings, and it also decides which hand you read — level 1 is the right hand, level 2 the left,
and 3 upward both. That coupling was the defect: reading the bass clef was possible only by being
rated at level 2, and the only way out of it was to be rated higher. Setup therefore offers
**Difficulty** (from my ratings, or level 1–10) and **Hands** (from the difficulty, right, left or
both), independently, so easy material in the bass clef and hard material in the right hand are both
available. Either can be let go from the × beside it in Practice, and both are remembered.

A pinned exercise **is scored and logged, and does not change the ratings** — you chose the
material, so it is not an assessment of you. The results panel says *not rated · you pinned it*
rather than leaving an unexplained absent change. The reason is arithmetic: a perfect run at pinned
level 1 against a rating of 900 is still worth about +2.6 under Elo, so twenty runs of easy
bass-clef drilling would move the rating about 50 points while you did easier work than usual —
and the rating is what chooses the automatic material.

## 5. The library

The **Library** section owns composers, pieces, the journal written about them, and the
associated media. It is the successor to a separate Rust desktop application; see
[ECOSYSTEM.md](ECOSYSTEM.md) for why the ecosystem is one web application rather than three
programs sharing a file.

**Pieces.** Browse grouped by composer or difficulty, filter, and read the journal and
recording catalogue for any piece. Each piece reports its *sight-reading fit* — the key and
starting level the exercise generator would use for it. A piece's status can be set to
*paused*, which removes it from the *Neglected* list: the status is the user's decision and
the list does not argue with it. The library can be sorted by last played or by time invested,
several pieces can be selected and re-statused at once, and filters and sort order are
remembered.

A new piece is created from the editor, which takes a title, opus, key, difficulty, status and
description, and can create a **composer inline** (`+ new composer…` in the composer list), so a
fresh installation needs nothing else. From a piece's detail view it is also possible to add
journal entries, edit the piece, attach a score, upload a recording, or delete it.

**Journal.** Entries carry tags and two ratings — how hard it felt and how well it went. The
feed can be filtered by tag, where a tag matches the label written rather than a word in the
prose. An entry can point at the recording it concerns; deleting the recording leaves the
prose intact.

**Passages.** A passage is a bar range and a note ("bars 12–14, the left-hand leaps"), with a
*Worked on it* action that stamps the date so untouched passages stay at the top. The
application cannot find these — it cannot see the score — but a passage can record that it
was seeded from a recording's A/B loop.

**Scores.** A PDF is shown in the browser's own viewer; MusicXML is engraved in the
application by the same renderer the exercises use. Neither is re-encoded: the file attached
is the file read. Both are validated on upload, so a `.pdf` that is not a PDF, or an XML file
that is not MusicXML, is refused before it can become a blank frame at the piano. A compressed
`.mxl` must be unzipped first. Scores are counted separately from recordings throughout.

**Recordings.** Each recording receives a waveform and an A/B loop. The peaks are decoded in
the browser, and clicking the picture moves the playhead. Markers are saved with the recording
rather than in the browser, so the same passage is available on the other machine. A recording
over 64 MB is not decoded for a picture, but still plays.

**Takes.** *Record takes* captures the piano while it is played — mono Opus at approximately
14 MB per hour, a convenience rather than an archive; the piano's own recording to a USB stick
remains the one to keep. A take opens on the first note and closes after the silence the server
treats as a segment boundary, so silence is not stored. It is attached to the passage it was
played in, which is decided once a playing has closed. Two takes can be compared side by side,
and either can be played at 0.85×, 0.7× or 0.5× — slower at the same pitch. A machine with no
audio input reports that instead of arming a switch that records nothing. Nothing is deleted
automatically; the System panel reports how much captured audio exists.

**Importing from `piano-progress`.** The one-click importer reads that database read-only and
can be run again to pick up changes while the older application is still in use. It refuses a
missing file or a database of the wrong shape rather than importing nothing quietly. Each
recording is reported as *in library*, *not copied yet* (still streamed from the old
directory), or *file missing*.

```bash
curl -X POST http://127.0.0.1:8000/api/repertoire/import \
     -H 'Content-Type: application/json' -d '{"copy_media": false}'
```

Recordings are copied into the ecosystem media directory by default; `"copy_media": false` skips
that step when the copy would be large.

## 6. Practice log

Everything played is logged without any action, once a MIDI device is connected: capture is a
standing switch rather than a per-sitting button. Notes are sent every two seconds, and whatever the
page is still holding when it goes away is handed to the browser to deliver after the document is
gone, so a reload, a kiosk restart or a power cut does not take the tail of the sitting with it. The server groups notes into **sittings** by
silence and into **segments** by shorter silence, which is normally one piece per segment.
Nothing is recomputed behind the user's back: a boundary moved by hand stays moved.

- **Segments** are cut at 8 seconds of silence, chosen by measuring a real 42-minute session.
  In that session the piece changes sat on gaps of 9.5 s and 11.7 s, while pauses *within* a
  piece sat at 15 s. No threshold is perfect, and this one errs toward more segments because
  merging one is a click while splitting one requires typing a position.
- **The Log view** shows today, the streak, a twelve-week calendar, time per piece, neglected
  pieces, and the sitting timeline. A segment can be tagged with a piece, split at a typed
  position (a clock value such as `1:30:12`, or seconds), merged with a neighbour, or
  re-segmented. Re-segmenting is the only destructive action and asks first when segments
  carry labels.
- **How time was spent** is a second axis from what was played. Each segment can be marked
  run-through, slow, section, hands-separate, from memory, warm-up or other, and the split of
  logged minutes adds up because uncharacterised segments keep their own bucket. The
  application may *offer* *slow* or *section* as a question with Yes/No; an offer counts for
  nothing until answered, never overwrites a chosen kind, and hands-separate is never guessed,
  because a register balance is not a measurement of the hands.
- **Workouts** are declared rather than inferred: *Start workout* … *Finish workout*.
  Everything inside the window is labelled sight-reading rather than mistaken for ordinary
  practice, and a finished workout links to the sitting it occurred in. Progress and Log then
  separate "how long did I play" from "how much deliberate sight-reading did I do". A workout
  can be started from any section.
- **A sitting ends when the piano does.** Switching the instrument off is taken as "I am done",
  so the sitting closes immediately rather than five minutes later. Turning it off mid-playing
  is not treated as a boundary — the server waits out a second and a half of silence first — so
  a USB interruption does not split a session. The Log refreshes itself while open.
- **Piece recognition.** Tagging a segment by hand makes it a reference; the next time similar
  material is played, the timeline offers the piece it believes it was, with the confidence and
  the arithmetic behind it. A sufficiently confident match is filled in automatically and
  marked *guessed*, with *It's right* and *Not this* beside it. Nothing is applied without a
  way to disagree, and correcting a guess is what teaches the matcher that two pieces sound
  alike. The **Recognising what you played** panel reports accuracy on the user's own library
  by hiding each tagged segment in turn, and reports how often automatically written labels
  survived review. One-hand drilling is the case it finds hardest, and the panel says so.
- **Pedal blur.** A blur is an attack that brought new harmony over notes the pedal was already
  holding. The count is reported with clock times, so "nine" is something that can be located
  in a long sitting. The rule is observed from the pitches rather than from a score.

Per piece, the Repertoire detail shows measured minutes from MIDI beside the minutes written in
the journal. They are deliberately not summed, because a session can be both measured and
written down, and adding them would count it twice.

**Edits apply immediately.** Labelling, splitting, merging and re-tagging apply the server's own
answer as it arrives and refresh only the totals. Reads about the library rather than about the
edit — the matcher's measured accuracy, machine health, the week's ratings — load when the view
opens instead of after every click, which is where a one-second stall per label came from.

`median_tempo` is a **note rate** over attack clusters — chords count as one attack, so they do
not read as infinite BPM. It is comparable with itself over time, not an absolute metronome
reading.

## 7. Progress

- **Rating over time.** Every rating change is recorded, so each skill has a curve rather than a
  single number. The Elo engine adjusts all nine dimensions on every attempt, so each point
  records whether its skill was that attempt's *focus*; the chart draws the whole line and
  reports how many points were focus attempts.
- **Recent exercises.** Selecting a row opens that attempt: its sub-scores, its counts, and the
  same player a fresh result receives — the performance, or the exercise as written, either hand.
- **This week.** Minutes over the last seven days, workouts and streak, the most improved skill,
  and the piece neglected longest.

**Every screen has an address.** `#/repertoire/piece/12`, `#/log/sitting/34` and
`#/stats/attempt/56` can be pasted between machines, and Back works. `/` or `Ctrl`/`Cmd`+`K`
opens a search over the library, the journal and recent sittings, and `1`–`3` switch sections.
Progress holds two views, **Ratings** and **Log**.

## 8. Playback

Two players exist because two different things are worth hearing.

- **After an attempt**, the results panel offers *Play yours*, *Play as written*, or either hand
  alone. Written notes are played at the tempo used for the count-in, and played notes carry the
  hands the scorer matched them to.
- **In the Log**, a sitting or a single segment can be played back from the notes themselves.
  Clicking anywhere on the timeline strip starts from there, and the transport moves the
  playhead in 30-second steps without losing the selected range. Notes are fetched on demand,
  because a long sitting contains thousands.

Three instruments are available, chosen in the Setup panel:

| Instrument | What it is | When it suits |
| --- | --- | --- |
| Through the piano | Notes are sent to a MIDI **output** to the instrument itself | Wherever a piano is connected. The only genuinely real piano sound, and it costs nothing |
| Sampled piano | The Salamander Grand Piano (a Yamaha C5), 30 samples | A viewer with no piano attached, or when the room should not be heard |
| Synthesiser | An FM voice built from Tone.js oscillators | Before the samples are installed, and as the fallback when nothing else is available |

The sampled piano is a one-time 2 MB download, fetched by the backend and served from the local
machine thereafter, so nothing at play time touches the network. A **Test** button plays a short
chord through the selected instrument, which distinguishes "the application is not playing" from
"this machine is not making sound".

The device bar reports the browser's audio state beside the instrument. A state of `suspended`
means the browser is waiting for a click before it will produce sound, and `audio ok` means the
application is playing into a machine whose speakers, sound server or tab-mute setting are
somebody else's problem. This readout is deliberately kept in the always-visible bar, because a
suspended audio context produces silence and reports no error anywhere else. The browser suite
measures the master output rather than trusting these readouts, since a "playing" indicator, a
running context and an advancing position are all compatible with a performance nobody can hear.

Recorded playback is faithful in *timing and touch*: every onset, duration and velocity is the
one the playing produced, because a note's length is measured at its release. The sustain pedal
is preserved — CC64 is stored as received and each note is held to the pedal-up covering its
release, so a pedalled chord rings on rather than stopping dead. In the passive log the two hands
cannot be separated, because the piano sends them on a single MIDI channel; a scored attempt can
separate them, because the exercise knows which hand each note belongs to.

**Falling notes.** A piano-roll view draws a keyboard along the bottom with notes falling onto
it, held notes drawn as long as they sound. It follows the playhead, so it is also a way to see a
hesitation that is hard to hear.

**Stop means stop.** There is a single player for the whole application, so nothing can play over
the top of anything else, and stopping cancels notes that were scheduled but had not sounded, as
well as sending note-off and all-notes-off to the instrument.

## 9. Health, backup and export

- **Nightly backups.** `python -m app.backup` writes `piano-ecosystem-<date>.json` into
  `SRT_BACKUP_DIR` and keeps the newest `SRT_BACKUP_KEEP` (14 by default). The installer enables
  a systemd timer at 03:10 with `Persistent=true`. The same code backs the *Download backup*
  action.
- **A System panel** reports database size and WAL state, recordings present, pending or missing,
  backups kept and the age of the newest, whether ALSA's sequencer is present, and which clients
  it can see — which is how "the piano is off" is distinguished from "the kernel module is
  missing".
- **Latency is suggested, never applied silently.** After a few attempts the device bar offers
  *Use N ms* when measured timing has been consistently early or late. Accepting it is a
  deliberate click, because it changes what the scorer subtracts and would make past scores
  incomparable.
- **Export.** *Progress › Log → Export & backup* downloads one JSON document containing every
  table: library, journal, media rows, sittings, note events, segments, workouts and ratings.
  Recording *files* are not included; the media directory is copied alongside. Restoring defaults
  to *add what is missing*, which never deletes local work; *replace everything* empties every
  table first and requires two clicks.

See [DEPLOYMENT.md](DEPLOYMENT.md) for running on the piano machine, WAL-aware backup and moving
between machines, and [`deploy/README.md`](../deploy/README.md) for the installed setup: a systemd
service, a Chromium kiosk at `localhost` (Web MIDI requires a secure context), the policy that
grants MIDI without a prompt, and the loopback boundary that keeps deletions on the piano machine.

## 10. Appearance

The **Appearance** control offers two independent choices:

- **Interface** — Auto (following the operating system), Light or Dark. Persisted, and applied by
  an inline script before first paint so a dark reload never flashes white.
- **Sheet music** — Themed, or always paper-white. Inverted notation divides readers, so it is a
  choice rather than a rule; the notation can be dark while the chrome is light, or the reverse.

The score's paper colour is deliberately independent of the chrome's theme, and the accent colour
lives in exactly one place (`frontend/src/app.css`), from which the chart palette is derived.

## 11. Viewing from another machine

The application can be opened from any machine on the LAN — for reading the library, reviewing
progress, or playing along with an exercise on a second device. Because the API is served over
the network rather than only on loopback, one boundary is enforced: **deletions are permitted
only on the piano machine.**

The interface reports the situation rather than disabling controls silently. A viewer page shows
the address it is being viewed from and states plainly that practice and calibration are not
available there; a delete control is disabled with an explanation of where it can be performed.
A viewer can never mistake a refused action for a broken one.

The panel also distinguishes a missing ALSA sequencer from a piano that is simply switched off,
which are otherwise indistinguishable symptoms with different causes.

See [DEPLOYMENT.md](DEPLOYMENT.md) for the loopback boundary and the kiosk configuration that
implements it.
