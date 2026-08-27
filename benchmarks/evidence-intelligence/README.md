# Evidence Intelligence component benchmarks

These benchmarks are intentionally narrower than `benchmarks/agent-investigation`. They validate deterministic evidence processing without claiming real-model reasoning or provider tokenizer savings.

## Correlation / reduction benchmark

Pipeline:

`Entity -> Correlation -> Grouping -> Reduction -> EvidencePackage`

Run:

```bash
python -m tracecite.evidence_benchmarking
```

The synthetic incident contains Bugly-like crash evidence, analytics events, client network evidence, an OTel-like backend span, repetitive client logs, and unrelated worker records. Required cross-source markers must survive while the package remains within its token budget.

## Deterministic exploration benchmark

Pipeline:

`Seed -> Provider Retrieval -> Entity Frontier -> Correlation -> Grouping -> Reduction -> EvidencePackage`

Run:

```bash
python -m tracecite.evidence_investigation_benchmarking \
  benchmarks/evidence-intelligence/cases/mobile-payment-crash
```

The case contains five independent JSON evidence providers and a deliberate chain:

```text
crash:C123
  -> app:session:S88
  -> edge:request:R19
  -> otel:trace:T22
  -> late payment callback
```

It also contains a different session/request as noise and repetitive client heartbeats. The benchmark requires the incident chain to be discovered without pulling the unrelated session, all required evidence to remain in the final package, Coverage to be complete, citations to remain recoverable, and the high-level `investigate` surface to collapse multiple structural retrieval rounds into one Agent-facing call.

The structural loop metric counts only deterministic entity-following rounds that produced new evidence. It demonstrates that those mechanical steps can be moved below the model; it is **not** a measurement of actual LLM calls or token usage.

## Claims boundary

These component benchmarks may prove:

- deterministic correlation and exploration behavior;
- bounded frontier/retrieval policies;
- evidence grouping/reduction;
- structural Agent-loop reduction potential;
- Evidence retention under a package budget;
- citation recovery.

They do **not** prove end-to-end Agent answer quality, real tokenizer savings, or actual model-loop reduction. Product-level claims require the external Agent Host matrix using the same model/prompt/data across `shell_rg`, `tracecite`, `tracecite_context`, `tracecite_intelligence`, and `tracecite_investigate`.
