"""The catalogue number: one canonical form, and the one guardrail on it.

`pieces.opus` is free text, and a real library proves what free text becomes: the same
catalogue number written four ways (`Op 10. No. 4`, `Op. 10 No. 3`, `Op . 78`, `w264`), plus
the same number twice in two cases (`w264` beside `W264`). The field is what tells two
pieces with the same title apart — two Chopin waltzes are both "Waltz" — so its consistency
is not cosmetic.

The rule is deliberately narrow. It knows `Op` and `No`, the abbreviations this library
uses, and a leading catalogue initial followed by its number (`D. 817`, `S.566a`, `W264`).
Anything else is passed through with its spacing tidied and nothing else touched: a value
the rule does not recognise must survive, because mangling it would lose information the
player typed and there is no second copy of it.

The canonical form is `Op. 27 No. 2` — the abbreviation carries a period, one space follows
it, and a period *after* the number is not the abbreviation's period:
`Op 10. No. 4` is `Op. 10 No. 4`, not `Op. 10. No. 4`.

The column has three writers and only two of them can name the rule. `store.create_piece` and
`store.update_piece` call it, and so does the legacy importer, which writes through a
table-generic upsert (`importer._upsert`) rather than through the store because it also matches on
`legacy_id` and must stay idempotent. The third is the backup restore, whose writer is generic on
purpose; a restored document is tidied by `schema._normalise_stored_opus` on the next startup,
which is also what canonicalises the rows already stored. One rule, three applications, and the
migration is the one that catches what the others cannot.
"""

from __future__ import annotations

import re

#: The one refusal, worded once. The client mirrors it for the editor's inline message, and
#: `frontend/src/lib/pieceOpus.ts` is the other half of this rule — change both or neither.
OPUS_NEEDS_A_NUMBER = (
    "An opus needs a number in it: the number is what tells two pieces with the same "
    "title apart. Write it as `Op. 27 No. 2` or `BWV 846`, or leave the field empty and "
    "put the note in the description."
)

_OP = re.compile(r"\bOp\b\s*\.?\s*", re.IGNORECASE)
_NO = re.compile(r"\bNo\b\s*\.?\s*", re.IGNORECASE)
#: A period that ends the catalogue *number* and is followed by `No.` — `Op. 10. No. 4`.
_NUMBER_THEN_NO = re.compile(r"(\d)\.\s+(?=No\.)")
#: A catalogue initial whose period is glued to its number — `S.566a`.
_INITIAL_THEN_NUMBER = re.compile(r"\b([A-Za-z])\.(?=\d)")
#: A catalogue initial that needs upper case — `w264`, which the same library also stores
#: as `W264`. Only a single leading letter immediately followed by a digit, so prose is not
#: shouted at.
_LEADING_INITIAL = re.compile(r"^([a-z])(?=\d)")


def normalise_opus(value: str | None) -> str | None:
    """The canonical form of a catalogue number, or None when there is none.

    Idempotent by construction, because the startup migration runs it over every row on
    every boot: a rule that changed its own output would report the schema as dirty for
    ever and rewrite the column each time.
    """
    if value is None:
        return None
    text = " ".join(value.split())
    if not text:
        return None
    text = _OP.sub("Op. ", text)
    text = _NO.sub("No. ", text)
    text = _NUMBER_THEN_NO.sub(r"\1 ", text)
    text = _INITIAL_THEN_NUMBER.sub(r"\1. ", text)
    text = _LEADING_INITIAL.sub(lambda match: match.group(1).upper(), text)
    return text.strip()


def opus_problem(value: str | None) -> str | None:
    """Why this catalogue number cannot be used, or None when it can.

    The only rule is that a value which is present must contain a digit. That is the field's
    entire purpose: a note that distinguishes nothing (`Sonata`, `Op.`) is worse than an
    empty field, because it looks like information and cannot disambiguate anything.
    """
    canonical = normalise_opus(value)
    if canonical is None:
        return None
    if not any(character.isdigit() for character in canonical):
        return OPUS_NEEDS_A_NUMBER
    return None
