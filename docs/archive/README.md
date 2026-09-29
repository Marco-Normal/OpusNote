# The historical record

Everything indexed here is **history**. It is kept because a record that is deleted takes its
reasoning with it — the plans record four places where the written plan was wrong and the code was
right, which is the most interesting thing in this repository — but none of it describes current
behaviour, and none of it should be read to find out how the application works today.

**That is not a stylistic preference, it is measured.** `FEATURES.md` documented a fixed 8-second
segment gap for two phases after the rule that replaced it landed, and four landed plans still said
`planned`. Neither broke a test, because no test can read a stale claim. So the material is marked
rather than trimmed: every `docs/PLAN-*.md` ends with a closing **historical-record** banner, and
`check_docs.py` refuses a document that carries one without declaring its `Status:`.

## Where to go instead

| You want | Read |
| --- | --- |
| How a feature behaves now | [`docs/FEATURES.md`](../FEATURES.md) |
| How it is built now | [`docs/ENGINEERING.md`](../ENGINEERING.md) |
| What a change may cost | [`docs/PERFORMANCE.md`](../PERFORMANCE.md) |
| The current phase status | the status line at the top of [`docs/ECOSYSTEM.md`](../ECOSYSTEM.md) |
| Which document a change obliges you to update | [`docs/ECOSYSTEM.md`](../ECOSYSTEM.md) § *The standing rule for documentation* |
| Which file owns a fact | [`AGENTS.md`](../../AGENTS.md) |

## The material

| Document | What it is |
| --- | --- |
| [`AGENT-LOG.md`](../../AGENT-LOG.md) | The append-only shared log. Never edited. Its rules and entry format are at the top of it |
| [`docs/ECOSYSTEM.md`](../ECOSYSTEM.md) | Phase status, the decision record, and the phase narrative. **Partly current** — its status line and phase table are the authority; its phase narratives are history |
| `docs/PLAN-*.md` | One implementation record per landed phase, with the measured numbers and the deviations |
| [`docs/ROADMAP.md`](../ROADMAP.md) | The original slice roadmap, superseded by ECOSYSTEM. Kept for its reasoning |
| [`docs/INTEGRATION-practice-logger.md`](../INTEGRATION-practice-logger.md) | The original two-project integration proposal, superseded by the merge. Kept for what it verified |
| [`docs/PLAN-SLICES1-7.md`](../PLAN-SLICES1-7.md) | Slices 2–7 of the test strategy — **the one plan that is not finished**. It stalled after Slice 1, and Slice 8 (`docs/TESTING.md`) is not written. This is open work, not history, and it is the exception in this list |

## Reading a plan without paying for all of it

Plans are long because they were written to be executed rather than skimmed. If you need one fact
from one, do not read the file front to back:

- The `**Status:**` line at the top says whether the phase shipped, and when.
- `ECOSYSTEM.md` § *Phase N* is the summary that `check_docs.py` cross-checks against that status.
- The document's own headings usually locate the decision in one section; read that section.
- `AGENT-LOG.md` holds the *verification* — which break scripts caught which break, and the
  measured numbers — where the plan holds the intent.
