"""Workouts: a deliberate, bounded set of sight-reading exercises.

A *workout* is declared — the player starts it and finishes it. A *sitting* is
emergent — it opens on the first note and closes after silence. They are not the
same object, and the schema says so: a workout points at the sitting it happened
inside, and the segments of that sitting are tagged from it.

This package exists rather than living in ``app/practice`` because a workout is
not a property of practice logging; it is the sight-reading side's unit of work,
and it happens to leave a trace in the log.
"""
