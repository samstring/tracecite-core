from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "docs/evidence-runtime-refactor-plan.zh-CN.md"


def replace_once(text: str, old: str, new: str) -> str:
    if old not in text:
        raise RuntimeError(f"plan anchor not found: {old[:100]!r}")
    return text.replace(old, new, 1)


def main() -> None:
    text = PATH.read_text(encoding="utf-8")

    text = replace_once(text, "# B. RetrievalSession 成为唯一 Evidence Memory Owner\n\n状态：**IN PROGRESS**", "# B. RetrievalSession 成为唯一 Evidence Memory Owner\n\n状态：**COMPLETE**")
    for line in (
        "- [ ] 同一 session 只有一个 canonical persisted state owner。",
        "- [ ] no-match operation 也可被记录，但不制造 Evidence。",
        "- [ ] parallel/atomic update regression 通过。",
        "- [ ] session state 不包含 hypothesis / root cause / sufficiency / stop recommendation。",
        "- [ ] Query A 首次命中 L100：body 可见。",
        "- [ ] Query B 再命中 L100：`new_evidence=0`，body suppress，但返回 `matched_existing_evidence` exact ref。",
        "- [ ] changed query 不会因为 dedup 丢 relevance。",
        "- [ ] replay exact Evidence body。",
        "- [ ] replay 返回 `replayed=true`。",
        "- [ ] replay 保持 `new_evidence=0`。",
        "- [ ] replay 不污染 recent novelty statistics。",
        "- [ ] 无 InvestigationState 时 canonical Evidence API 完整工作。",
        "- [ ] InvestigationState executions 不再作为 seen/range primary owner。",
        "- [ ] RetrievalSession 不读取 hypothesis/finding 决定 retrieval。",
    ):
        if line in text:
            text = text.replace(line, line.replace("- [ ]", "- [x]"), 1)

    text = replace_once(text, "# C. 重建 Canonical Evidence API\n\n状态：**TODO**", "# C. 重建 Canonical Evidence API\n\n状态：**COMPLETE**")
    for line in (
        "- [ ] caller-supplied target/predicate/scope。",
        "- [ ] 返回 Evidence + Coverage + Provenance + Novelty。",
        "- [ ] zero-match 为 retrieval fact，不变成 absence proof。",
        "- [ ] EvidencePointer/source-version range 可精确展开。",
        "- [ ] 已覆盖 range 可 suppress duplicate body。",
        "- [ ] immutable source identity 校验保持。",
        "- [ ] 至少覆盖当前 4-case 中常见的 count/group/distinct 需求。",
        "- [ ] aggregation result 仍有 scope/source-version/provenance。",
        "- [ ] 不需要 raw source dump 到 Agent context。",
        "- [ ] source/hash/manifest/integrity mechanical verification 保持。",
        "- [ ] caller-supplied predicate 可机械验证时使用统一 result contract。",
    ):
        if line in text:
            text = text.replace(line, line.replace("- [ ]", "- [x]"), 1)

    text = replace_once(text, "# D. `investigate` 收敛为 `traverse`\n\n状态：**TODO**", "# D. `investigate` 收敛为 `traverse`\n\n状态：**COMPLETE**")
    for line in (
        "- [ ] Runtime 不自行选择“更重要”的 sibling/entity。",
        "- [ ] Runtime 不生成 `next_best_entity` / `next_query`。",
        "- [ ] frontier 仅用于 mechanical traversal execution，不代表 investigation order。",
        "- [ ] `identifier_only_correlation_safe=false` 等 identity constraints 保持。",
    ):
        if line in text:
            text = text.replace(line, line.replace("- [ ]", "- [x]"), 1)

    text = replace_once(text, "# E. Routing / Selection 收敛\n\n状态：**TODO**", "# E. Routing / Selection 收敛\n\n状态：**COMPLETE**")
    for line in (
        "- [ ] routing unit tests 检查仅依赖 mechanical transport facts。",
        "- [ ] generic signal hints 不声称 causal relevance。",
        "- [ ] full match set 可恢复。",
        "- [ ] truncation/omission 显式。",
    ):
        if line in text:
            text = text.replace(line, line.replace("- [ ]", "- [x]"), 1)

    text = replace_once(text, "# F. Host Observation Contract\n\n状态：**TODO**", "# F. Host Observation Contract\n\n状态：**IN PROGRESS**")
    for line in (
        "- [ ] `140039` 中 `grep/bash/read` 不再从 trajectory telemetry 消失。",
        "- [ ] `139417` 中 TraceCite/native 40/40 类混合深挖可完整观察。",
        "- [ ] opaque shell 明确标 `opaque`，不伪装成 canonical Evidence。",
    ):
        if line in text:
            text = text.replace(line, line.replace("- [ ]", "- [x]"), 1)

    for line in (
        "- [ ] `supported` 要求 direct evidence/citation。",
        "- [ ] `inference_supported` 要求 qualified inference。",
        "- [ ] `unsupported_from_log` 奖励明确 evidence boundary。",
        "- [ ] inference/unsupported 被说成 direct fact 计 overclaim。",
    ):
        if line in text:
            text = text.replace(line, line.replace("- [ ]", "- [x]"), 1)

    text = replace_once(text, "# H. 文档与 Adapter 收敛\n\n状态：**TODO**", "# H. 文档与 Adapter 收敛\n\n状态：**IN PROGRESS**")

    evidence = r'''

---

## 6. 2026-08-30 本轮 canonical 收敛证据回填

> 下表按第 4 节强制格式记录。本表只关闭已经有 commit + gate 证据的工作项；4-case / repeated A/B 尚未运行，因此 I/J 不提前打勾。

### B — RetrievalSession canonical owner

Status: **COMPLETE**  
Commit: `a7baa1d971d375c482431b54f45776d215c51f11`  
Tests: canonical final gate `33317449637`；包含 `test_runtime_session_retrieval.py`、`test_session_novelty_regressions.py`、canonical Evidence contract 与 architecture check。  
Why: 删除并行 retrieval sidecar/state ownership，保证 novelty、covered range、replay/repeated relevance 只有一个机械 owner。  
Behavior change: changed-query repeated hit 保留 `matched_existing_evidence`；replay 明确为旧 Evidence reread 且不增加 novelty；canonical Evidence API 可脱离 InvestigationState 工作。  
Remaining risk: 真实 Pi 长轨迹下的行为价值仍需 I/J benchmark 验证。

### C — Canonical Evidence API

Status: **COMPLETE**  
Commit: `a7baa1d971d375c482431b54f45776d215c51f11`  
Tests: canonical final gate `33317449637`；顶层 public-surface assertion 强制包含 `retrieve/materialize/replay/aggregate/traverse/verify`。  
Why: 删除多套半重叠入口，把 evidence acquisition/recovery/aggregation/verification 收敛成一个稳定 contract。  
Behavior change: `tracecite.__all__` 直接暴露 canonical primitives；`AggregateRequest` 正式进入 public surface；旧错误 API 不作为顶层 canonical contract。  
Remaining risk: Pi/MCP/Mobile adapter 的上层同步在 I/J 后再做。

### D — Traverse mechanical boundary

Status: **COMPLETE**  
Commit: `a7baa1d971d375c482431b54f45776d215c51f11`  
Tests: canonical final gate `33317449637`；canonical contract / runtime boundary / architecture check。  
Why: 删除 Runtime “调查者”语义，避免 Core 决定 investigation order。  
Behavior change: public contract 使用 `EvidenceTraversal / TraversalLimits / traverse`；caller owns seed/scope/direction；frontier 只表示 mechanical traversal。  
Remaining risk: 真实 Agent 是否因此减少无效深挖只能由 I/J 验证。

### E — Routing / Selection mechanical semantics

Status: **COMPLETE**  
Commit: `a7baa1d971d375c482431b54f45776d215c51f11`  
Tests: canonical final gate `33317449637` 中 `tests/test_evidence_routing.py`、`tests/test_evidence_selection.py` PASS。  
Why: 防止 transport heuristic 变成因果/优先级/stop policy。  
Behavior change: routing/selection 只使用 mechanical transport facts；lossy selection 必须保留 truncation/omission/recovery 语义。  
Remaining risk: 不同 source density 下的质量/成本影响留给 I/J。

### F1 — Pi Host Tool Activity Ledger

Status: **COMPLETE**  
Commit: `c95f2eeaa1885745bcea8fd684325bff09fcebaf`  
Tests: Host/eval focused gate `33318061265`；`tests/test_pi_host_tool_activity.py`、`tests/test_pi_session_to_transcript.py`、architecture check PASS。  
Why: TraceCite-local retrieval telemetry 看不到 Agent 切回 `grep/read/bash` 的真实 trajectory。  
Behavior change: Pi extension 从真实 `tool_call/tool_result` 记录 TraceCite/native activity；`grep/find`=native search，`read`=native read，`bash`=native other 且 `opaque=true`；activity 可写入 `TRACECITE_PI_ACTIVITY`，transcript 保留 activity/duration/summary。  
Remaining risk: F2 optional checkpoint 未实现/未验证；是否有产品价值不能从 F1 推断。

### G1 — Support-aware scoring becomes canonical scorer behavior

Status: **COMPLETE**  
Commit: `c95f2eeaa1885745bcea8fd684325bff09fcebaf`  
Tests: Host/eval focused gate `33318061265`；`tests/test_root_cause_benchmarking.py`、`tests/test_support_aware_root_cause_benchmarking.py`、support self-test PASS。  
Why: 避免 benchmark 通过外部 overlay 才理解 direct / inference / unsupported evidence boundary。  
Behavior change: `tracecite.root_cause_benchmarking.score_transcript()` 直接应用 `supported / inference_supported / unsupported_from_log`；canonical `passed` 即 support-aware 结果，同时保留 `legacy_passed` 诊断字段；旧 `support_level_score.py` 仅保留 compatibility helper。  
Remaining risk: G2/G3 的 case-level truth/infra validity 仍要在新的真实 A/B 中确认。

### H1 — Agent integration doc

Status: **COMPLETE**  
Commit: `3c2c39e6605cebb565d8c3ce3d367b0e2e99c734`  
Tests: docs-only change；后续 Core CI 作为 repository integrity gate。  
Why: 删除与 Guardrails 冲突的 normative investigation playbook。  
Behavior change: `docs/agent-integration.md` 只定义 canonical Evidence API、RetrievalSession、routing/selection、Host telemetry、evaluation 与 trust boundary；示例明确为 non-normative。  
Remaining risk: 中文 integration doc 尚未在本项要求中同步；若对外发布双语文档，应在 Core contract 稳定后一起校准。

### H2 — Two skills use final canonical API semantics

Status: **COMPLETE**  
Commit: `.agents/skills/tracecite-investigate/SKILL.md` = `8040a8c292ae7bf5f3e3e894b6b40d6ee7364844`；`.pi/skills/tracecite/SKILL.md` = `3b1359a30ef9e5cf30e00020fb8e91a3afb38cd7`。  
Tests: docs/skill integrity through Core CI；canonical code semantics already gated by `33317449637` and `33318061265`。  
Why: 防止 skill 继续教授旧 `search/expand/investigation` 作为第二套架构。  
Behavior change: 两份 skill 以 `retrieve/materialize/replay/aggregate/traverse/verify` 为唯一 canonical semantics；Pi `tracecite_search/tracecite_expand` 只作为 adapter mapping 描述。  
Remaining risk: MCP/Mobile 依然按 H3/K 明确暂缓，不能提前同步。

### Cleanup evidence

- canonical C/D one-shot cleanup commit: `a7baa1d971d375c482431b54f45776d215c51f11` 自删 canonical helper/workflow。
- Host/eval one-shot cleanup commit: `6f4ec266b5468b891d006ec03ca4e33fd112bd9d`。
- 当前进入 I 前的原则：**先跑第一个小 case `kubernetes-140039-runc-5347-scale`；确认入口、Host activity、canonical scorer 与 A/B artifact 正常后，才允许扩到其余 3 case。**
'''

    if "## 6. 2026-08-30 本轮 canonical 收敛证据回填" not in text:
        text = text.rstrip() + evidence + "\n"

    PATH.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
