"""Practice-logging domain.

A port of the standalone ``practice-logger`` app into this one, not a rewrite:
the sessionizer, gap segmentation with frozen boundaries, the idempotent ingest
and the attack-clustering tempo rule all arrive unchanged, with their tests.

What changed in the port, and why:

* **One owner.** The original read the Rust app's ``piano.db`` and never wrote a
  library table. Here the library is ours (:mod:`app.repertoire`), so
  ``segments.piece_id`` is a real foreign key to ``pieces`` and the "never write
  their tables" discipline is gone — it existed only to let two processes share
  a file.
* **Vocabulary.** ``practice_sessions`` is ``sittings``: a *sitting* is an
  emergent stretch at the piano, a *workout* is a deliberate set of exercises,
  and a *segment* is one piece (or one workout) inside a sitting.
* **No double capture.** Capture is one path in one app, so the hazard the
  original documented at length cannot occur.

Deliberately not ported: self-similarity identification (the original's Phase 3,
never implemented) and its ``identification_corrections`` table. With no matcher
there is nothing to correct, and a table nothing writes is dead weight.
``segments.confidence`` and ``segments.identified_by`` remain, so a matcher can
be added later without a migration.
"""
