# RCAEval MB-scale Native vs TraceCite benchmark

This benchmark is for large-evidence root-cause investigation, not automatic answer scoring.

## Goal

Compare the same Pi/model on the same multi-MB incident evidence with only the evidence-access path changed:

- Native: `read,bash,grep,find,ls`
- TraceCite: `tracecite_search,tracecite_expand`

Correctness is reviewed manually from the final answer against the public RCAEval ground truth and the actual telemetry. Objective telemetry is collected automatically.

## Data source

Use the public MIT-licensed RCAEval RE2/RE3 telemetry hosted at Hugging Face. Prefer RE3 when we want code-level faults and RE2 when we want infrastructure/resource/network faults.

Do not expose the original RCAEval case directory name to the agent. RCAEval case names encode the root-cause service and fault class, so the preparation stage must copy telemetry into neutral file names before either arm runs.

## Evidence representation

Parquet is converted losslessly enough for investigation into neutral text files:

- `logs.jsonl`
- `traces.jsonl` when available
- `metrics.csv`
- `incident.txt` containing only neutral incident context and the known incident-onset timestamp
- `evidence-manifest.json` containing only objective byte/row counts

The source case id, root-cause service, and injected fault are never placed in the agent evidence directory.

## Leakage isolation

Preparation and agent execution are separate jobs.

1. The preparation job is the only job that knows the RCAEval source case id.
2. It uploads a neutral evidence artifact.
3. The run job downloads only that artifact.
4. Native runs before the TraceCite repository is checked out on the runner, so its filesystem tools cannot discover the benchmark manifest or source case from the checkout.
5. TraceCite runs after checkout, but its agent tool list contains only TraceCite evidence tools and the evidence boundary points only at the neutral evidence directory.

## Prompt

Both arms receive the same investigation task:

> A production incident occurred in a Train Ticket microservice deployment. The supplied telemetry covers the incident window and `incident.txt` gives the known onset time. Determine the root-cause service and the concrete failure mechanism. Explain the causal chain from the root cause to downstream symptoms. Use only supplied evidence, cite exact evidence lines for material claims, and stop once the root cause is sufficiently supported rather than performing confirmatory searches.

The Native arm additionally says to use only files in the current working directory. The TraceCite arm additionally says that all telemetry must be obtained through TraceCite.

## Correctness policy

No regex/concept scorer decides correctness.

For each final answer, manual review records one of:

- `correct`: root-cause service is correct and the claimed mechanism is supported by telemetry.
- `partial`: root-cause service is correct but the mechanism is materially incomplete/overstated.
- `incorrect`: wrong root-cause service or causal explanation.

For RCAEval RE3, the reviewer should also verify that the answer identifies a concrete root-cause indicator (for example a stack trace/error path) rather than merely naming a service.

Review should be blind to arm when practical.

## Objective telemetry to keep

For both arms:

- evidence bytes and row counts by modality
- exit code
- wall seconds
- input tokens
- output tokens
- cache-read tokens
- model calls
- tool calls
- final answer
- full transcript

TraceCite additionally keeps:

- evidence access count
- allowed/blocked retrievals
- block reasons
- `positive`, `neutral_no_match`, `redundant`, `error`
- constrained notices

These are measurements, not correctness scores.

## Scale plan

After the pilot, select cases by expanded text evidence size, not compressed Parquet size:

- 5-15 MB: 3 cases
- 15-30 MB: 3 cases
- 30-60 MB: 3 cases
- 60-100 MB: 3 cases

Keep systems/faults diverse. Run each case twice per arm with the same model configuration. That gives 12 cases x 2 arms x 2 repeats = 48 runs.

## Pilot case

Start with RCAEval `re3tt_ts-route-service_f3_6` from RE3 Train Ticket.

Public case-index metadata reports:

- 30-minute window
- 316 metric series
- 71,952 log rows
- 242,715 trace rows
- incident onset: Unix `1733674797`

The source case id is used only by the preparation job. The agent sees neutral file names and the onset time, not the encoded service/fault label.

The pilot first measures the expanded text size. If it is below 5 MB, reject it before spending model calls and select a larger case.