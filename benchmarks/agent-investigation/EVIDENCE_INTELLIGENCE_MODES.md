# Evidence Intelligence model-level benchmark modes

This document extends the experimental Agent benchmark with controlled raw-evidence baselines and Evidence Intelligence modes.
It does not change the stable Extension Protocol v2 contract.

## Modes

The complete comparison matrix is:

1. `shell_rg` — constrained raw-evidence baseline exposing only bounded `rg_search` and `read_lines` tools.
2. `free_shell` — a stronger realistic baseline: the Agent freely chooses read-only local analysis commands and arguments inside the isolated evidence workspace (`rg`, `jq`, `cat`, `sed`, `head`, `tail`, `find`, `wc`, `sort`, `uniq`, `ls`). It receives no network tool and no arbitrary shell/code execution surface.
3. `tracecite` — bounded TraceCite search/expand transport.
4. `tracecite_context` — TraceCite plus cross-turn seen-Evidence suppression.
5. `tracecite_intelligence` — the Agent still chooses retrieval operations, but returned canonical evidence may be correlated, grouped, deterministically reduced, token-budgeted, and projected as an EvidencePackage.
6. `tracecite_investigate` — exposes the high-level deterministic investigation path. TraceCite may expand stable Evidence IDs / EntityRefs through providers under an ExplorationPolicy, then correlate/group/reduce/package the result. The Agent still owns hypotheses, causality, and the final diagnosis.

`free_shell` exists to answer the stronger practical question: whether TraceCite still reduces model/tool loops when the baseline Agent can choose normal local investigation utilities rather than being limited to a purpose-built search tool.

`tracecite_intelligence` separates the value of evidence selection from the value of moving mechanical retrieval loops below the model. `tracecite_investigate` is the mode intended to test Agent-loop reduction.

## Fairness

All six modes must use the same model/version, system prompt, Agent-visible question, source data, overall wall-clock/tool budget, stopping rules, and evaluator. Only the tool surface changes.

`free_shell` is intentionally sandboxed to the copied benchmark evidence directory. Its subprocess environment does not inherit provider credentials. Mutating, network-capable, or arbitrary-code execution paths are not part of this baseline.

Do not give either experimental mode evaluator-only hints, root-cause labels, issue discussions, or provider-specific semantic shortcuts. Automatic expansion may only follow identities/relations present in retrieved evidence and must obey the same bounded evidence universe available to the other modes.

## Context state

`tracecite_context`, `tracecite_intelligence`, and `tracecite_investigate` receive a fresh per-run `TRACECITE_BENCH_CONTEXT_ID`. Canonical evidence remains recoverable even when repeated Agent-facing rows are suppressed.

## Required measurements

A publishable comparison must report at least:

- provider-reported model input/output tokens when available;
- model calls;
- tool calls;
- `search` / `expand` / `investigate` calls separately;
- model-visible tool-output characters;
- duplicate visible evidence;
- wall time;
- root-cause correctness;
- required Evidence recall;
- citation resolution accuracy;
- for correlated modes, correlation precision/recall when the case defines gold relations.

A cheaper run that fails correctness or required Evidence recall does not win.

## Claims boundary

The synthetic multi-source benchmark under `benchmarks/evidence-intelligence` may prove deterministic exploration, boundedness, structural loop reduction, citation recovery, and evidence retention. It cannot prove real model token savings or diagnosis quality. Those claims require an external Agent Host run through `run_host.py` with the matrix above.
