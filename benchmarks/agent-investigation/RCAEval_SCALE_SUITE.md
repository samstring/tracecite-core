# RCAEval Four-Case Scale Regression Suite

This document is the canonical record for the fixed RCAEval scale regression used to compare Native evidence access against TraceCite on real public telemetry. The same four cases are shared by the Pi and Codex hosts so host changes do not silently change the benchmark corpus.

## Official source

- Benchmark: RCAEval
- Repository: `phamquiluan/RCAEval`
- Dataset: `https://huggingface.co/datasets/phamquiluan/RCAEval`
- Suite/system: `RE3-TT` / Train Ticket
- Agent-visible evidence for this scale suite: **only** each case's official `traces.parquet`, converted deterministically to newline-delimited JSON with `pandas.DataFrame.to_json(..., orient="records", lines=True, force_ascii=False)`.
- Gold metadata stays evaluator-only. The case ID, root-cause service, fault label, and injection metadata must not be placed in the Agent prompt or evidence directory.

RCAEval documents RE3 as a multi-source code-level-fault benchmark and provides annotated root-cause service/root-cause indicators. This scale suite deliberately fixes the system and trace format so the main changing variable is evidence size, while still using distinct real failures rather than duplicating records.

## Fixed four cases

| Tier | RCAEval case | Official root-cause service | Official fault | Traces | Expected JSONL size before first measured run | Status |
| --- | --- | --- | --- | ---: | ---: | --- |
| S1 | `re3tt_ts-auth-service_f1_4` | `ts-auth-service` | `f1` | 36,374 | ~11.4 MB | estimate; replace with measured bytes |
| S2 | `re3tt_ts-auth-service_f1_1` | `ts-auth-service` | `f1` | 88,159 | ~27.7 MB | estimate; replace with measured bytes |
| S3 | `re3tt_ts-route-service_f1_1` | `ts-route-service` | `f1` | 173,320 | ~54.4 MB | estimate; replace with measured bytes |
| S4 | `re3tt_ts-route-service_f3_6` | `ts-route-service` | `f3` | 242,715 | **76,145,385 bytes (~76.1 MB)** | measured in the candidate-first profile |

The first three MB values are estimates derived from trace-count ratio against S4. They are not acceptance truth. Every benchmark run must record the actual converted JSONL byte count, row count, and SHA-256; this document should be updated when the first full four-case run establishes those values.

## Paired model routing

This suite follows the repository's Dual-GMI policy:

- **Native / GMI1:** `GMI_API_KEY` + `GMI_MODEL`
- **TraceCite / GMI2:** `GMI2_API_KEY` + `GMI2_MODEL`
- Endpoint: `https://api.gmi-serving.com/v1`

The two arms use the same TraceCite Core commit, the same generic question, and byte-identical `traces.jsonl` evidence. GMI1 and GMI2 may point at the same model family, but the exact configured model IDs must be recorded in artifacts.

For Codex, each arm gets its own `CODEX_HOME`. The Native home has no TraceCite MCP configuration; the TraceCite home enables only the six canonical TraceCite MCP tools. Codex uses the repository's standard-MCP configuration path and a pinned CLI version in the workflow.

## Agent question

The question is intentionally generic and must not reveal the RCAEval case name, service, fault label, or injection timestamp:

> Using only the supplied `traces.jsonl`, investigate the incident. Identify the single most likely root-cause microservice and explain the concrete failure mechanism or root-cause indicator visible in the traces. Reconstruct enough causal/temporal evidence to distinguish root cause from downstream symptoms. Cite exact `traces.jsonl:L<line>` locations for material claims. Distinguish direct observation from inference. Do not use case-name/injection metadata or outside knowledge.

## Evidence boundary

### Pi

Native may inspect `traces.jsonl` with the normal Pi read/grep/bash/find/ls surface. TraceCite must inspect or derive runtime-evidence content through the formal TraceCite evidence tools; native evidence access is guarded by the benchmark extension.

### Codex

Native runs with normal Codex read-only workspace access and no TraceCite MCP server. TraceCite runs with the standard TraceCite MCP server and developer instructions that require all evidence inspection/derivation to use TraceCite.

A **valid Codex TraceCite run must satisfy all three boundary gates**:

- at least one canonical `tracecite_*` MCP call;
- zero `command_execution` / native shell evidence calls in the normalized transcript;
- a non-empty final answer.

`benchmarks/agent-investigation/standard_mcp_benchmark.py validate-transcript --host codex` is the contract checker. A bypass attempt invalidates the comparison rather than being silently accepted. This is intentionally stricter than merely prompting Codex to prefer TraceCite.

## Validation

RCAEval's official case metadata is the independent root-cause truth used here. The automated scorer treats the following separately:

1. **Service gold:** the final answer must identify the official root-cause service.
2. **Mechanism / indicator support:** the answer must state a concrete mechanism/indicator and ground it in cited trace evidence. Until an exact official per-case indicator mapping is pinned in this repository, this is an evidence-support metric rather than a brittle exact-string gold match.
3. **Citation grounding:** material claims must cite valid `traces.jsonl:L<line>` locations; at least one cited line must support the selected root-cause service. Invalid/out-of-range citations fail the grounding gate.
4. **Boundary validity:** TraceCite must make real TraceCite runtime-evidence calls and must not obtain runtime-evidence content through native tools.

The official `f1` / `f3` labels are recorded as evaluator metadata. They are not exposed in the prompt and are not required as literal answer text unless a future scorer pins a natural-language mapping for those code-level faults.

## Measurements to retain

For every case and arm retain at least: actual evidence bytes/rows/SHA-256, model ID, exit/provider status, wall time, root-cause service result, mechanism/indicator evidence support, citation grounding, model/tool call counts, provider token usage when available, TraceCite evidence-call count, native-command count, and TraceCite boundary-contract result.

Native is a baseline: a Native failure remains comparison evidence. TraceCite service/citation/boundary failure is a candidate failure; provider quota/rate/unavailability is infrastructure-inconclusive and must not be silently recast as product failure.

## Canonical workflows

- Pi: `.github/workflows/pi-rcaeval-four-scale-dual-gmi-ab.yml`
- Codex CLI/app-server: `.github/workflows/codex-rcaeval-four-scale-dual-gmi-ab.yml`

The Codex workflow is manual-dispatch by default. `scope=smoke` runs S1 only; `scope=four` runs the full four-case suite. It downloads official RCAEval data, converts it to deterministic JSONL, creates byte-identical Native/TraceCite workspaces, configures separate GMI1/GMI2 Codex homes, runs Codex through `codex app-server`, validates the TraceCite-only evidence contract, scores citations/root-cause service, and uploads per-case plus aggregate artifacts.

## Historical S4 performance reference

The earlier candidate-first search-only profile on `re3tt_ts-route-service_f3_6` measured 76,145,385 bytes / 242,715 JSONL records. Three search probes improved from roughly 59 seconds on the prior path to 7.40s, 8.45s, and 11.90s on candidate-first. That result is a retrieval-performance reference only; the four-case suite above is an end-to-end Agent RCA comparison.
