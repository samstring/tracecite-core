# Investigation timeline and structural comparison

`tracecite.runtime.investigation_compare` provides two read-only primitives:

```python
from tracecite.runtime.investigation_compare import (
    compare_investigations,
    timeline_investigation,
)

timeline = timeline_investigation("investigation.json")
delta = compare_investigations("before.json", "after.json")
```

Both functions accept a validated `InvestigationState`, an
`InvestigationStore`, a state mapping, or a JSON path. Paths and mappings are
checked against bounded source-size limits before canonical state validation.
They never write state, read a Knowledge store, run tools, or inspect source
files referenced by Evidence pointers.

## Timeline

`timeline_investigation` returns a versioned `kind: "timeline"` envelope with
the investigation ID, snapshot revision, and stable control events for:

- investigation creation;
- Hypothesis, Test, Execution, and Finding records;
- Knowledge Candidate links; and
- the stop transition, when present.

Events are ordered by the bounded timestamp text (missing timestamps sort last),
event kind, and ID. Same-time ties therefore have deterministic ordering. The
envelope carries the current snapshot revision; event rows contain only IDs,
statuses/outcomes, control timestamps, and relationship IDs. Claim text, summaries,
operation text, stop details, parameters, Evidence
URIs/bodies, artifact paths, and domain payloads are intentionally absent.

`max_events` bounds the returned event list. `counts.total`,
`counts.reported`, `counts.omitted`, `omitted.events`, and `truncated` make
omission explicit. `max_output_chars` is a second hard cap; if it is reached,
the implementation trims deterministic lists and retains a compact control
envelope rather than slicing JSON. Invalid, corrupt, missing, or oversized
sources return `status: "error", valid: false, error: {"code": ...}` by
default. `strict=True` raises `InvestigationCompareError` with the stable code.

## Structural comparison

`compare_investigations(left, right)` compares two snapshots, including two
revisions of the same state file supplied as separate mappings or paths. The
result includes:

- left/right source metadata, revisions, statuses, and revision delta;
- counts and bounded ID `added`/`removed`/`changed` sets for observations,
  hypotheses, tests, executions, findings, and candidate links;
- structural outcome transitions for hypotheses, executions, and findings;
- budget usage and policy-change flags;
- generic coverage declaration, omission, truncation, missing-evidence, and
  Finding limitations deltas;
- stop presence/kind changes; and
- candidate-link additions, removals, and status/link-field changes.

Changed entries report structural field names and IDs only. They do not expose
the values of claims, summaries, query parameters, Evidence references,
artifacts, stop details, or candidate payloads. This is a structural diff, not
an anomaly detector, causal analysis, or epistemic judgment.

`max_items` bounds each ID/change/transition list. Per-list and top-level
`omitted` counters are retained when limits trim output. All output is bounded
by `max_output_chars` and deterministic for the same validated inputs.

## Public integration

Both functions are exported by `tracecite` and `tracecite.runtime`. The CLI
exposes the same read-only operations:

```bash
tracecite investigation timeline investigation.json
tracecite investigation compare before.json after.json
```

They are not tool-dispatcher operations and do not create an Execution. Hosts
must preserve the source/limit/error envelope and must not turn a structural
delta into an automatic Finding, stop transition, or Knowledge proposal.
