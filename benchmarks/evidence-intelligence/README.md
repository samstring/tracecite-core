# Evidence Intelligence component benchmark

This benchmark is intentionally narrower than `benchmarks/agent-investigation`.
It exercises the deterministic pipeline added on the experimental branch:

`Entity -> Correlation -> Grouping -> Reduction -> EvidencePackage`

Run:

```bash
python -m tracecite.evidence_benchmarking
```

The synthetic incident contains Bugly-like crash evidence, analytics events,
client network evidence, an OTel-like backend span, 180 repetitive client log
records, and 60 unrelated worker records. The benchmark requires all four
cross-source incident markers to survive while the package remains within its
token budget.

This benchmark proves only component-level compression and evidence retention.
It does **not** prove end-to-end Agent answer quality or real tokenizer savings.
Those claims remain gated by the existing real-agent benchmark comparing
`shell_rg`, `tracecite`, and `tracecite_context` under the same model/prompt.
