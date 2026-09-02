# Dual-GMI Parallel Pi A/B Policy

This policy is the default for future Native vs TraceCite benchmark comparisons.

## Routing

- Native arm: `GMI_API_KEY` + `GMI_MODEL`
- TraceCite arm: `GMI2_API_KEY` + `GMI2_MODEL`
- Both use `https://api.gmi-serving.com/v1` unless a benchmark explicitly documents another GMI endpoint.

## Execution

- Native and TraceCite arms start in parallel.
- Each arm runs in a separate GitHub Actions job and therefore a separate runner process/filesystem boundary.
- Each arm gets its own `PI_CODING_AGENT_DIR`, source checkout, session directory, result directory, and process tree.
- TraceCite gets its own MCP state directory.
- The two arms must use the same TraceCite Core commit, the same pre-fix source commit, the same benchmark question, and byte-identical runtime evidence.

## Evidence boundary

- Native uses normal Agent-native runtime evidence access.
- TraceCite runtime evidence must go through TraceCite MCP.
- A TraceCite comparison is invalid if it makes zero TraceCite MCP evidence calls.
- A TraceCite comparison is invalid if native runtime-evidence access is observed in the TraceCite arm.

## Comparison

The compare stage runs only after both arm jobs finish. It records at least:

- model used by each arm
- run validity
- root-cause accuracy
- evidence-chain completeness/boundedness
- evidence-boundary compliance
- fresh/cached/input/output token usage
- model call count
- TraceCite MCP call count
- TraceCite native-evidence contamination count
- evidence/source/Core identity checks

The canonical workflow for this policy is `.github/workflows/pi-dual-gmi-parallel-ab.yml`.
