"""Practice-domain facade re-exporting focused submodules.

Callers and tests import from ``app.practice.store``; the implementation lives in
sibling modules (``store_core``, ``materialise``, ``edits``, ``analytics``,
``rhythm``, ``references``, ``autotag``).
"""

from __future__ import annotations

from .. import db
from ..config import settings
from . import calibration
from . import schema as practice_schema
from . import shingles
from .analytics import (
    GRACE_WINDOW_DAYS,
    STREAK_LOOKBACK_DAYS,
    Streak,
    _fill_days,
    _minutes,
    _today,
    by_piece,
    calendar,
    kinds_breakdown,
    neglected,
    piece_practice,
    sources,
    streak,
    summary,
    tempo_series,
)
from .autotag import (
    _autotag_rows,
    _candidate_out,
    _chosen_first,
    _decode_sitting,
    _has_outcome,
    _outcome_counts,
    _piece_labels,
    _record_outcome,
    _score_and_decode_sitting,
    _sequence_verdict,
    _shares,
    autotag_sitting,
    autotag_unlabelled,
    candidates_for_sitting,
    identification_quality,
    resolve_identification,
    segment_identification,
)
from .edits import (
    _counted_kind,
    _segment_or_raise,
    _settle_label,
    assign_piece,
    merge_segments,
    resegment_sitting,
    set_practice_kind,
    split_segment,
)
from .materialise import (
    _PASSAGES,
    _PASSAGES_KEEP,
    _backfill_blur_positions,
    _passage_rows,
    _passages_derived,
    _piece_tempo_baseline,
    _refresh_metrics,
    _segment_config,
    _segment_rows,
    _tag_from_workouts,
    awaiting_segments,
    ensure_segments,
    offer_practice_kinds,
    sitting_detail,
)
from .references import (
    _REFERENCES,
    _adjust_pooled,
    _database_name,
    _features_from,
    _fingerprints,
    _fingerprints_from,
    _incremental_references,
    _labelled_rows,
    _notes_for_segments,
    _notes_in_range,
    _pool_features,
    _pooled_signatures,
    _reference_inputs,
    _reference_version,
    _segment_features,
    _updated_features,
    cached_references,
    examples_from,
    forget_references,
    labelled_count,
    references_from,
)
from .rhythm import (
    _correlation_at_lag,
    _hour_chunks,
    _round,
    _utc_offset_minutes_now,
    rhythm,
)
from .store_core import (
    CLOSE_LOOKBACK_MS,
    CLOSE_QUIET_MS,
    _SEGMENT_COLUMNS,
    _SETTLED,
    CloseOutcome,
    ConfirmationRequired,
    InvalidRequest,
    NotFound,
    _find_sitting,
    _sitting_notes,
    close_open_sitting,
    ingest,
    list_sittings,
    list_sittings_conn,
    local_date,
    sitting_notes,
    utc_text,
)

SCHEMA = practice_schema.PRACTICE_SCHEMA
migrate = practice_schema.migrate
