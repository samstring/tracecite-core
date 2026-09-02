# TraceCite Agent 对比数据

[English](benchmark-results.md)

状态：`feature_for_agent` CA258 基线的已验证 paired measurements。更新时间：2026-09-02。

## 怎么理解这些数字

这里是相同模型条件下 Native vs TraceCite 的 paired Agent 实测。它们只代表指定 Host / Model / Prompt / Case 组合，**不表示 TraceCite 在所有模型、所有 incident 上都固定节省某个百分比**。

评估顺序坚持 correctness-first：

1. Run 必须 infrastructure-valid；
2. 答案质量 / Evidence support 不能实质退化；
3. provenance / recoverability 必须保持；
4. 最后才比较 context / token / model call / tool call 效率。

Provider 429、quota、outage 或 harness failure 单独标记为 infrastructure-invalid，不作为模型或产品失败统计。

## 已验证的 bounded Pi 方法

正式 paired run 共用 system prompt：

```text
You are a coding agent investigating supplied runtime evidence. Keep the investigation bounded. Once the root cause is sufficiently supported, answer immediately instead of performing confirmatory searches. Cite exact evidence lines for material factual claims.
```

Native 追加：

```text
Use only evidence from files in the current working directory and do not use external knowledge.
```

TraceCite 追加：

```text
Follow the user's explicit request to use TraceCite. All runtime-evidence content must be obtained through TraceCite tools; do not use native file-access tools for the evidence.
```

TraceCite arm 只通过 Pi adapter 暴露 `tracecite_search` / `tracecite_expand`，并显式加载 `.pi/skills/tracecite/SKILL.md`。

## Suite A：4 个公开 root-cause case，双重复

Case：

1. containerd #6772
2. Kubernetes #140039 / runc #5347
3. Kubernetes #141283 compatibility feature gate
4. Kubernetes #141402 PodCertificate readiness

模型：MiniMax M3。4 case × 2 repeat，共 8 个 paired output。

| 指标 | Native | TraceCite | TraceCite 变化 |
|---|---:|---:|---:|
| Pass | 6 / 8 | 6 / 8 | 持平 |
| Concept recall | 78.125% | 87.500% | +9.375 pp |
| Evidence marker recall | 93.750% | 90.625% | -3.125 pp |
| Input tokens | 543,333 | 341,232 | -37.2% |
| Output tokens | 89,533 | 52,644 | -41.2% |
| Cache-read tokens | 23,973,873 | 5,991,938 | -75.0% |
| Model calls | 530 | 195 | -63.2% |
| Tool calls | 477 | 357 | -25.2% |
| Input + output | 632,866 | 393,876 | -37.8% |
| Input + output + cache | 24,606,739 | 6,385,814 | -74.0% |

Workflow run：https://github.com/samstring/tracecite-core/actions/runs/33620265562

这组数据支持：scorer Pass 持平，平均 Concept Recall 提高，Marker Recall 略低，同时模型输入、cache、model round 和 tool call 都显著降低。

## Suite B：MB 级真实公开 Evidence，双重复

Case：

- Longhorn #7843：模型可见原始 Evidence 约 17.8 MB。
- Harvester #6253：模型可见原始 Evidence 约 7.7 MB。

测试分支严格从 CA258 的 Agent / Skill / Runtime 基线创建，只增加 case/workflow 文件。模型：MiniMax M3。2 case × 2 repeat，共 4 个 paired output。

| 指标 | Native | TraceCite | TraceCite 变化 |
|---|---:|---:|---:|
| Pass | 2 / 4 | 2 / 4 | 持平 |
| Concept recall | 87.5% | 87.5% | 持平 |
| Evidence marker recall | 75.0% | 75.0% | 持平 |
| Input tokens | 494,553 | 289,824 | -41.4% |
| Output tokens | 32,836 | 34,194 | +4.1% |
| Cache-read tokens | 13,193,560 | 3,078,682 | -76.7% |
| Model calls | 276 | 83 | -69.9% |
| Tool calls | 193 | 196 | +1.6% |
| Input + output | 527,389 | 324,018 | -38.6% |
| Input + output + cache | 13,720,949 | 3,402,700 | -75.2% |

Workflow run：https://github.com/samstring/tracecite-core/actions/runs/33638574962

### Longhorn 汇总

| 指标 | Native | TraceCite |
|---|---:|---:|
| Pass | 2 / 2 | 2 / 2 |
| Input tokens | 269,345 | 120,760 |
| Output tokens | 18,190 | 11,567 |
| Cache-read tokens | 6,075,402 | 633,725 |
| Model calls | 116 | 25 |
| Tool calls | 72 | 50 |

变化：Input -55.2%，Cache -89.6%，Model calls -78.4%，Tool calls -30.6%。

### Harvester 汇总

| 指标 | Native | TraceCite |
|---|---:|---:|
| Concept recall | 87.5% | 100% |
| Evidence marker recall | 50% | 50% |
| Input tokens | 225,208 | 169,064 |
| Output tokens | 14,646 | 22,627 |
| Cache-read tokens | 7,118,158 | 2,444,957 |
| Model calls | 160 | 58 |
| Tool calls | 121 | 146 |

变化：Input -24.9%，Cache -65.7%，Model calls -63.8%，Tool calls +20.7%，Output +54.5%。

这说明一种很重要的行为：TraceCite 可以用更多定向 Evidence operation 换取更少的模型 round/context replay；“Tool Call 更少”不是它节省上下文的必要条件。

## Scorer caveat

上表严格保留 raw scorer 输出，不人工补分。

人工复查 Longhorn gmi1 时发现，TraceCite 最终答案明确写了旧 `NodeUnpublishVolume` **发生在**新 Pod `NodePublishVolume` **之后**。这和 gold 的“new publish before old unpublish”逻辑完全等价，但 concept regex 只识别正向措辞，因此漏判。这属于 scorer false-negative，不是 retrieval miss。

Longhorn gmi2 则不同：Publish / Unpublish 相关证据已经被取到，但最终答案没有把新旧 Pod 事件显式配成那条 temporal edge。这是 evidence synthesis gap，而不是 evidence availability 问题。

Harvester 的 Fail 主要是严格 exact-marker/citation presentation 没满足；TraceCite 两次 Harvester 的 Concept Recall 都是 100%。

## 这些数据能支持什么

当前验证可以支持以下有限结论：

- 在这些 bounded Pi case 上，TraceCite 能在保持整体 scorer root-cause 质量可比的同时，显著降低 input/cache/model-round 成本。
- 节省并不简单来自“更少 Tool Call”。MB suite 中 Tool Call 几乎相同（193 vs 196），但 Model Call 从 276 降到 83，Cache-read Token 降 76.7%。
- 收益依赖 Evidence topology 和 Agent 行为；高选择性、局部证据的 `grep` 仍然是很强的 baseline。
- Correctness / Evidence boundary 是接受门槛。Token 更少但 timeout、overclaim 或关键因果证据缺失，不算产品收益。

## 这些数据不能证明什么

这些 run 不能证明：

- 每一次 TraceCite query 都比 `grep` / `rg` 小；
- 所有模型都有同样的节省比例；
- Evidence 越大，TraceCite 相对优势一定越大；
- scorer 能完美识别所有语义等价表达；
- Token 少本身就等于诊断更好。

后续新增 benchmark 结果时，必须保留 model、prompt、case、run validity、raw scorer output 和 usage totals，保证结果可审计、可复现。
