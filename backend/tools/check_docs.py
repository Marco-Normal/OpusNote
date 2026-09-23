#!/usr/bin/env python3
"""Check the documentation against itself and against the code.

    backend/.venv/bin/python backend/tools/check_docs.py

This is the enforcement of the standing rule in `docs/ECOSYSTEM.md` § *The standing rule for
documentation*. That rule is a habit until something checks it, and a habit nobody checks is the
reason `ECOSYSTEM.md` described a shipped phase as **Planned** for three commits.

Two classes of finding, and the difference matters:

* **Gate** — objective and always the author's to fix: a link or anchor that does not resolve, a
  document no index reaches, a plan whose status disagrees with the phase table, a landed plan
  still carrying a "Next step: execute" footer. Any of these exits non-zero.
* **Canary** — a heuristic. A handful of exact phrases whose re-introduction would mean a bug this
  repository already fixed has come back. It is printed and does not fail the run, because a
  heuristic that can be wrong must never be a gate: an operator who cannot trust a red light
  learns to ignore it.

What it deliberately does not check: whether a *claim* is true. `FEATURES.md` saying "8 seconds"
was wrong for two phases, and no checker can read intent. That is what the trigger table is for.

Exit codes: 0 clean (canaries may still be printed), 1 at least one gate failed, 2 the tool could
not do its job (a missing file it needs, an unparseable structure) — and it says which, rather
than reporting a clean run it has not earned.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
README = ROOT / "README.md"
DOCS = ROOT / "docs"
ECOSYSTEM = DOCS / "ECOSYSTEM.md"

#: Docs are discovered, not listed: a new document is checked the moment it exists. Binary
#: assets under `docs/images/` are not documentation and are skipped by the suffix filter.
def markdown_files() -> list[Path]:
    files = [README, ROOT / "THIRD-PARTY.md", ROOT / "AGENT-LOG.md", ROOT / "deploy" / "README.md"]
    files += sorted(DOCS.glob("*.md"))
    return [f for f in files if f.exists()]


def slug(heading: str) -> str:
    """GitHub's heading anchor: lowercase, punctuation dropped, spaces to hyphens."""
    text = heading.strip().lower().replace("`", "")
    text = re.sub(r"[^a-z0-9 \-_]", "", text)
    return text.replace(" ", "-")


def headings(text: str) -> set[str]:
    return {slug(m.group(1)) for m in re.finditer(r"^#{1,6}\s+(.*)$", text, re.M)}


def fenced_lines(text: str) -> set[int]:
    """1-based line numbers inside ``` fences — a link shown as an example is not a link."""
    inside: set[int] = set()
    open_at = None
    for n, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("```"):
            if open_at is None:
                open_at = n
            else:
                inside.update(range(open_at, n + 1))
                open_at = None
    if open_at is not None:
        inside.update(range(open_at, len(text.splitlines()) + 1))
    return inside


def check_links(files: list[Path], failures: list[str]) -> int:
    """Every relative link resolves, and every `#anchor` names a heading that exists."""
    anchor_cache = {f: headings(f.read_text(encoding="utf-8")) for f in files}
    checked = 0
    for f in files:
        text = f.read_text(encoding="utf-8")
        skip = fenced_lines(text)
        for m in re.finditer(r"\[[^\]]*\]\(([^)\s]+)\)", text):
            line = text[: m.start()].count("\n") + 1
            if line in skip:
                continue
            target = m.group(1)
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            checked += 1
            path, _, frag = target.partition("#")
            if path:
                resolved = (f.parent / path).resolve()
                if not resolved.exists():
                    failures.append(
                        f"{f.relative_to(ROOT)}:{line}: link does not resolve: {target}"
                    )
                    continue
                if frag and resolved in anchor_cache and frag not in anchor_cache[resolved]:
                    failures.append(
                        f"{f.relative_to(ROOT)}:{line}: anchor does not exist in "
                        f"{resolved.relative_to(ROOT)}: #{frag}"
                    )
            elif frag and frag not in anchor_cache[f]:
                failures.append(f"{f.relative_to(ROOT)}:{line}: anchor does not exist: #{frag}")
    return checked


def check_every_doc_is_reachable(files: list[Path], failures: list[str]) -> int:
    """Each `docs/*.md` must be the target of a link from the README.

    A document nothing links to is a document nobody reads, and this repository proved what
    happens next: fifteen of its twenty-one documents were unreachable from the front page, and
    several of those were the stale ones.

    It resolves the *links*, not the path text. The first version searched for the string
    `docs/TEST-DATA.md` anywhere in the README, so replacing the link with backticked prose left
    the check green — which its own falsification caught, and which is the whole reason
    `backend/tools/falsifications/make_a_document_unreachable.sh` exists.
    """
    text = README.read_text(encoding="utf-8")
    skip = fenced_lines(text)
    linked: set[Path] = set()
    for m in re.finditer(r"\[[^\]]*\]\(([^)\s]+)\)", text):
        line = text[: m.start()].count("\n") + 1
        if line in skip:
            continue
        target = m.group(1)
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        path, _, _frag = target.partition("#")
        if path:
            linked.add((README.parent / path).resolve())
    for doc in sorted(DOCS.glob("*.md")):
        if doc.resolve() not in linked:
            failures.append(
                f"README.md: no link to {doc.relative_to(ROOT)} — a document nothing reaches "
                f"goes stale"
            )
    return len(list(DOCS.glob("*.md")))


PHASE_ROW = re.compile(r"^\|\s*(\d+)\s*\|(.*)$")


def phase_table() -> dict[int, tuple[int, str]]:
    """ECOSYSTEM's phase table: phase number -> (line number, row text).

    Scoped to the one table whose header is `| # | Phase | Delivers | Risk |`; the document has
    a dozen other tables whose first column is a number, and reading those would invent rows.
    """
    text = ECOSYSTEM.read_text(encoding="utf-8")
    lines = text.splitlines()
    start = next(
        (i for i, l in enumerate(lines) if l.startswith("| # | Phase | Delivers | Risk |")), None
    )
    if start is None:
        raise SystemExit(
            "refusing to report a clean run: ECOSYSTEM.md has no `| # | Phase | Delivers | Risk |` "
            "table, so status agreement cannot be checked"
        )
    rows: dict[int, tuple[int, str]] = {}
    for i in range(start + 2, len(lines)):
        m = PHASE_ROW.match(lines[i])
        if not m:
            break
        rows[int(m.group(1))] = (i + 1, lines[i])
    return rows


def declared_status(path: Path) -> tuple[str, int] | None:
    """The plan's own status word, and the line it is on. None when it declares none."""
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines()[:14], 1):
        m = re.match(r"\*\*Status:\s*\**\s*([A-Za-z]+)", line) or re.match(
            r"Status:\s*`?\s*([A-Za-z]+)", line
        )
        if m:
            return m.group(1).lower(), n
    return None


def row_status(row: str) -> str | None:
    """`landed` / `planned` when the row carries one inline, else None.

    Rows 1-12 deliberately carry no inline status — the table's preamble says the status line
    holds the rest — so `None` is a normal answer, not a missing one. Matching is case-insensitive
    because a row reads `**20a–20e landed.**`.
    """
    for word in ("landed", "planned"):
        if re.search(r"\*\*[^*]*" + word + r"[^*]*\*\*", row, re.I):
            return word
    return None


#: `Phases 1-13 and 15-23 are landed. Phase 14 is planned.` — the one line that must agree with
#: the table for every phase the table leaves unmarked.
STATUS_CLAUSE = re.compile(r"Phases?\s+([\d\sand,\-]+?)\s+(?:are|is)\s+(landed|planned)", re.I)


def status_line_sets() -> tuple[set[int], set[int]]:
    """(landed, planned) phase numbers, read from ECOSYSTEM's status line."""
    text = ECOSYSTEM.read_text(encoding="utf-8")
    line = next((l for l in text.splitlines() if l.startswith("Status:")), None)
    if line is None:
        raise SystemExit(
            "refusing to report a clean run: ECOSYSTEM.md has no `Status:` line, so phases the "
            "table leaves unmarked cannot be checked"
        )
    landed: set[int] = set()
    planned: set[int] = set()
    for spec, word in STATUS_CLAUSE.findall(line):
        for part in re.split(r",|\band\b", spec):
            part = part.strip()
            span = re.fullmatch(r"(\d+)\s*-\s*(\d+)", part)
            single = re.fullmatch(r"(\d+)", part)
            if span:
                numbers: object = range(int(span.group(1)), int(span.group(2)) + 1)
            elif single:
                numbers = [int(single.group(1))]
            else:
                continue
            (landed if word.lower() == "landed" else planned).update(numbers)
    if not landed and not planned:
        raise SystemExit(
            f"refusing to report a clean run: ECOSYSTEM.md's status line did not parse "
            f"({line.strip()!r}); keep it in the form 'Phases A-B and C-D are landed. Phase E is "
            f"planned.' so it can be checked"
        )
    return landed, planned


def check_status_agreement(failures: list[str], notes: list[str]) -> int:
    """A plan and the phase table must not disagree about whether the work shipped."""
    rows = phase_table()
    line_landed, line_planned = status_line_sets()
    compared = 0
    for plan in sorted(DOCS.glob("PLAN-PHASE*.md")):
        m = re.match(r"PLAN-PHASE(\d+)", plan.name)
        if not m:
            continue
        phases = [int(m.group(1))]
        if "-" in plan.name.split("PHASE", 1)[1]:  # PLAN-PHASE8-9.md covers two rows
            tail = plan.name.split("PHASE", 1)[1].removesuffix(".md")
            phases = [int(p) for p in re.findall(r"\d+", tail)]
        declared = declared_status(plan)
        if declared is None:
            notes.append(f"{plan.relative_to(ROOT)}: no `**Status:**` line to compare")
            continue
        word, line = declared
        for phase in phases:
            if phase not in rows:
                failures.append(
                    f"{plan.relative_to(ROOT)}:{line}: describes phase {phase}, but ECOSYSTEM.md's "
                    f"phase table has no row {phase}"
                )
                continue
            row_line, row = rows[phase]
            inline = row_status(row)
            source = "table row"
            if inline is None:
                # The table leaves this phase unmarked, so the status line is the authority.
                source = "status line"
                if phase in line_landed:
                    inline = "landed"
                elif phase in line_planned:
                    inline = "planned"
                else:
                    notes.append(
                        f"ECOSYSTEM.md:{row_line}: phase {phase} is marked neither in the table "
                        f"nor in the status line, so {plan.name} ({word}) is not cross-checked"
                    )
                    continue
            compared += 1
            if inline != word:
                failures.append(
                    f"{plan.relative_to(ROOT)}:{line}: says **{word}**, but ECOSYSTEM.md marks "
                    f"phase {phase} **{inline}** ({source}, line {row_line}) — one of them is stale"
                )
    return compared


def check_no_execute_footer(files: list[Path], failures: list[str]) -> int:
    """A landed plan must not end by telling the next agent to execute it.

    Four landed plans carried `Next step: execute with the executing-plans skill`, which is an
    instruction to re-run finished work.
    """
    checked = 0
    for plan in sorted(DOCS.glob("PLAN-*.md")):
        declared = declared_status(plan)
        if declared is None or declared[0] != "landed":
            continue
        checked += 1
        text = plan.read_text(encoding="utf-8")
        for n, line in enumerate(text.splitlines(), 1):
            if line.lstrip().startswith("**Next step:") or line.lstrip().startswith("Next step:"):
                failures.append(
                    f"{plan.relative_to(ROOT)}:{n}: landed plan still carries a Next step — "
                    "reword it, or it invites a re-run of finished work"
                )
    return checked


#: Exact phrases whose return means a bug this repository already fixed has come back. Kept short
#: on purpose: every entry is a known-wrong claim, not a style preference.
CANARIES: list[tuple[str, str, str]] = [
    ("four-voice writing", "ENGINEERING.md §3", "the generator writes at most two voices"),
    ("eight seconds of silence", "FEATURES.md §6", "Phase 22a replaced the fixed segment gap"),
    ("Every threshold lives in", "ENGINEERING.md §5", "four scoring constants are hardcoded"),
    ("the README's configuration table", "DEPLOYMENT.md", "the table moved to ENGINEERING.md §8"),
    ("twelve-week calendar", "FEATURES.md §7 / ECOSYSTEM.md", "the default is 30 days"),
    ("scale and fault injection", "TEST-STRATEGY.md / check.sh", "no such tier exists"),
]


def canaries(files: list[Path]) -> list[str]:
    hits = []
    for f in files:
        text = f.read_text(encoding="utf-8")
        for n, line in enumerate(text.splitlines(), 1):
            for needle, where, why in CANARIES:
                if needle in line:
                    hits.append(f"{f.relative_to(ROOT)}:{n}: {where}: {why}")
    return hits


def main() -> int:
    files = markdown_files()
    failures: list[str] = []
    notes: list[str] = []

    links = check_links(files, failures)
    docs = check_every_doc_is_reachable(files, failures)
    compared = check_status_agreement(failures, notes)
    plans = check_no_execute_footer(files, failures)
    hits = canaries(files)

    print(f"check_docs: {len(files)} files, {links} relative links")
    print(
        f"  index: {docs} documents all reachable from README.md"
        if not any("no link to" in f for f in failures)
        else f"  index: {docs} documents, some unreachable (below)"
    )
    print(f"  status: {compared} plan/phase pairs compared, {plans} landed plans checked for footers")

    if notes:
        print("\nnotes (not failures):")
        for n in notes:
            print(f"  note  {n}")

    if hits:
        print("\ncanaries (report only — a stale phrase this repository fixed once):")
        for h in hits:
            print(f"  warn  {h}")

    if failures:
        print(f"\n{len(failures)} documentation failure(s):")
        for f in failures:
            print(f"  FAIL  {f}")
        print(
            "\nSee docs/ECOSYSTEM.md § *The standing rule for documentation* for what each "
            "document owes."
        )
        return 1

    print("\ncheck_docs passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:  # a checker that cannot run must not look like a clean run
        print(f"check_docs could not complete: {exc!r}", file=sys.stderr)
        raise SystemExit(2)
