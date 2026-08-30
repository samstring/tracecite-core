from pathlib import Path

path = Path('docs/evidence-runtime-refactor-plan.zh-CN.md')
text = path.read_text(encoding='utf-8')
text = text.replace('# A. 删除 Runtime 越界语义\n\n状态：**TODO**', '# A. 删除 Runtime 越界语义\n\n状态：**COMPLETE**', 1)
text = text.replace('- [ ] Runtime public result 不再出现 `ready_for_reasoning`。\n- [ ] Runtime public result 不再出现 `stop_recommended`。\n- [ ] `new_evidence=0` regression 仍明确只是 retrieval fact。\n- [ ] Guardrail test 禁止重新引入这些字段。', '- [x] Runtime public result 不再出现 `ready_for_reasoning`。\n- [x] Runtime public result 不再出现 `stop_recommended`。\n- [x] `new_evidence=0` regression 仍明确只是 retrieval fact。\n- [x] Guardrail test 禁止重新引入这些字段。', 1)
anchor = '## A2. 删除 skill 中任何 stop/sufficiency 暗示\n'
evidence = '''### A1 完成证据（2026-08-30）\n\n- Runtime contract commits: `fce60a9`, `24de41d`, `08019cd`, `b2c397d`, `e3cb96e`, `f0cbe192`。\n- `EvidenceReadiness / ReadinessStatus / StopKind / StopReason / ready_for_reasoning / stop_recommended` 已从 Runtime public progress contract 删除。\n- `no_new_evidence` 改为 `data.novelty` retrieval fact；不再生成 stop reason。\n- 只有明确 bounded acquisition end（例如 frontier/source exhausted）可返回 `acquisition_end_reason`。\n- Focused gate run `33314454449`: `21 passed in 1.53s`；`scripts/check_architecture.py` PASS。\n- 一次性 refactor helper/workflow 已在结果 commit 中自删除，不形成长期维护层。\n\n'''
if evidence not in text:
    text = text.replace(anchor, evidence + anchor, 1)
text = text.replace('- [ ] `.pi/skills/tracecite/SKILL.md` 只解释 API/evidence semantics。\n- [ ] `.agents/skills/tracecite-investigate/SKILL.md` 同样不提供 investigation strategy。\n- [ ] 没有 benchmark-specific clue。', '- [x] `.pi/skills/tracecite/SKILL.md` 只解释 API/evidence semantics。\n- [x] `.agents/skills/tracecite-investigate/SKILL.md` 同样不提供 investigation strategy。\n- [x] 没有 benchmark-specific clue。', 1)
a2_anchor = '\n---\n\n# B. RetrievalSession 成为唯一 Evidence Memory Owner\n\n状态：**TODO**'
a2_evidence = '''\n### A2 完成证据（2026-08-30）\n\n- 审核 `.pi/skills/tracecite/SKILL.md` 与 `.agents/skills/tracecite-investigate/SKILL.md`。\n- 当前两份 skill 已明确：Agent owns hypotheses/order/causal reasoning/sufficiency/stopping；`new_evidence=0`、`no_match`、`session_progress`、identity constraints 均仅为机械事实。\n- 未发现 benchmark hidden answer / preferred investigation path；因此本项不为制造 diff 而修改 skill。\n- operation/API 名称后续随 canonical API 收敛在 H2 统一更新。\n\n---\n\n# B. RetrievalSession 成为唯一 Evidence Memory Owner\n\n状态：**IN PROGRESS**'''
if a2_anchor not in text:
    raise SystemExit('phase B anchor not found')
text = text.replace(a2_anchor, a2_evidence, 1)
path.write_text(text, encoding='utf-8')
