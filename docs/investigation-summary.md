# Investigation completeness summary (v1)

`tracecite.runtime.investigation_summary.summarize_investigation()` is a
read-only, bounded view of a validated `InvestigationState`. It accepts a
state object, JSON mapping, `InvestigationStore`, or state-file path. Loading
never writes the store or changes a revision. A corrupt, missing, or oversized
source returns a small `status: "error"` envelope; callers that need fail-fast
behavior may pass `strict=True`.

The result is advisory metadata, not an enforcement funnel and not an
epistemic verdict. It does not copy hypothesis claims, finding summaries,
parameters, evidence bodies, or raw tool data. Detail rows reference only
bounded IDs, statuses, and generic gap categories. Counts cover observations,
hypotheses (including hypotheses without a Test), tests, executions, and findings. The execution counters separate
error, unknown, missing evidence, recording omission, and recording
truncation. `stop` reports the state and bounded stop reason when present.

`suggested_actions` uses stable, domain-neutral categories: `formulate_test`,
`execute_test`, `gather_missing_evidence`, `seek_contradiction`,
`record_finding`, and `stop/reopen`. Suggestions are options for an Agent to
consider; no category is mandatory and the module never invents a hypothesis
or a domain query. `advisory_completeness.complete` means only that this
bounded coordination view found no listed gap. It does not prove that the
investigation is correct, exhaustive, or safe to close.

The summary has schema version `1`. Detail lists are capped at 32 items by
default (at most 24,000 serialized characters); `omitted` counts and the
`truncated` flag identify bounded output. Callers may request smaller positive
integer limits, but hard ceilings remain in force. Invalid negative,
non-numeric, or below-minimum limits return a bounded `invalid_limit:*` error
envelope using the module's default safe output ceiling; they are never
silently widened into an unbounded request.
