# Evidence Intelligence 工作进度与交接

> 本文档用于记录 `experiment/evidence-intelligence` 分支当前工作状态、已验证事实、未完成事项、风险点与后续执行顺序，便于中断后继续开发，或交接给新的 Agent / 开发者继续执行。

更新时间：2026-08-28

## 1. 当前工作基线

- 仓库：`samstring/tracecite-core`
- 当前工作分支：`experiment/evidence-intelligence`
- 当前 HEAD：`e8f0e41be3ac9f6c47a811eb65f2e1b82facc616`
- HEAD commit：`feat(runtime): add explainable evidence progress state`
- 本阶段工作只在 `experiment/evidence-intelligence` 上继续，不直接修改 `main` / `refactor/agent-v2`。
- 实验最终是否合并回稳定分支，取决于真实 Agent benchmark 是否能够证明 token、tool/model loop、evidence recall、correctness、citation 与资源开销方面具有明确收益。

## 2. 当前目标

当前阶段不是继续扩大功能面，而是验证 Evidence Intelligence 是否真正能够让 Agent 在大规模 evidence 上：

1. 少重复读取已经覆盖过的 evidence；
2. 少执行只返回旧 evidence 的重复搜索；
3. 在 bounded memory 下保留更有价值的异常信号；
4. 在不丢失关键证据和 citation 的前提下降低 token；
5. 将 25KB / 5MB 的已验证路径扩展到 50MB、100MB、500MB；
6. 在第一个失败规模停止扩容，先定位并修复真实瓶颈。

TraceCite 的边界保持不变：Runtime 负责机械证据状态、关联、压缩、coverage 和 retrieval progress，不负责替 Agent 做根因推理。

## 3. 已完成工作

### 3.1 Evidence Intelligence 主体实验能力

实验分支已经具备 EvidenceProvider、Evidence Graph / correlation、Grouping / Reducer、token-aware EvidencePackage、Context Delta、自动 Entity exploration 等实验能力。

这些能力已经覆盖组件级 boundedness、evidence retention、URI recovery、namespace 隔离和结构性 Agent-loop 下沉验证。

### 3.2 Evidence Progress 状态模型

commit `e8f0e41` 已新增 explainable evidence progress state。

当前已经有用于表达以下概念的 runtime 数据结构 / tracker：

- evidence requirement；
- evidence gap；
- evidence delta；
- readiness；
- coverage / range 状态；
- retrieval completion / no-growth 状态。

注意：**状态模型已经存在，但还没有完整接入 canonical `inspect/get/search` 工具执行路径。**

### 3.3 当前 HEAD 的基础 CI

当前 HEAD `e8f0e41` 已验证：

- `Evidence Intelligence Benchmark`：成功，run `33151909192`；
- `Core CI`：成功，run `33151909183`。

因此当前继续开发的基线是 green，可以在这个 HEAD 上继续做小步改动。

### 3.4 大文件 fixture/build

通用 scale-build workflow 已采用较适合大文件的增量生成 / 校验方向，说明大规模 fixture 构建本身已有部分 streaming 基础。

但 real-agent 50MB workflow 仍存在整体读文件的路径，尚不能直接认为能够安全扩展到 100MB / 500MB。

## 4. 当前未完成事项

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| EvidenceProgress 数据结构 / tracker | ✅ 已完成 | 已进入 runtime |
| EvidenceProgress 接入 `inspect/get/search` | ❌ 未完成 | 当前最优先的代码工作之一 |
| duplicate `get` hard stop | 🟡 部分完成 | benchmark host 只覆盖 exact tuple；缺 coverage-aware 判断 |
| duplicate `search` hard stop | 🟡 部分完成 | 只覆盖 exact query；缺“不同 query 但只有旧 evidence”的判断 |
| 统一 `NO_NEW_EVIDENCE` runtime 语义 | 🟡 部分完成 | benchmark host 有局部实现，core runtime 未统一 |
| 256 signal signature severity-aware retention | ❌ 未完成 | 容量满后高严重度新信号可能被早期低严重度噪声挡住 |
| 50MB real workflow streaming | ❌ 未完成 | 仍需消除大文件 whole-file read 路径 |
| 50MB failure 根因闭环 | ⚠️ 未完成 | 已确认失败 run，但尚未拿到可证明的具体失败原因 |
| 修改后 25KB / 5MB regression | ❌ 未执行 | 必须在核心改动完成后重新跑 |
| 50MB rerun | ❌ 未执行 | 必须等前置改动与 regression 通过 |
| 100MB real-agent gate | ❌ 未执行 | 只有 50MB 通过后才能继续 |
| 500MB real-agent gate | ❌ 未执行 | 只有 100MB 通过后才能继续 |

## 5. 50MB 当前断点

已经存在一次真实 50MB Agent benchmark 失败：

- Workflow：`TraceBench 50MB Real Agent`
- Run ID：`33150972050`
- Workflow 文件：`.github/workflows/evidence-tracebench-50mb-real.yml`
- Head SHA：`fdf20d590557cc0634743a35da649fbd90e552ca`
- 结果：`failure`

**目前只能确认“这个 run 失败了”，不能确认失败根因。**

后续继续开发时，必须先尽可能取得该 run 的 failed step / job log / artifact，然后才能把问题分类为：

- TraceCite 实现问题；
- benchmark host / workflow 问题；
- 大文件内存 / I/O 问题；
- 模型/API 调用问题；
- quota / rate limit；
- 其他外部环境问题。

禁止在没有日志证据的情况下把 50MB failure 归因于某一类原因。

## 6. 下一阶段严格执行顺序

### Step 1：关闭 50MB failure 的事实缺口

优先取得 run `33150972050` 的：

- failed job；
- failed step；
- job log；
- workflow artifact（如果存在）。

如果 GitHub connector 无法返回日志，也要明确记录“无法取得的具体数据”，不要用猜测补全。

### Step 2：把 EvidenceProgress 接入 canonical runtime tool path

目标：`inspect/get/search` 每次执行后都能更新确定性的 evidence progress。

需要做到：

- 成功读取后更新 coverage；
- 新 evidence 更新 delta；
- 无新增 evidence 更新 no-growth；
- gaps / readiness 保持可解释；
- 不把根因判断放入 tracker；
- 不把 benchmark-only 状态机当成最终 runtime contract。

### Step 3：实现 coverage-aware `get` Hard Stop

不再只判断完全相同的 `(start, end)`。

如果一次新的 `get` 请求范围已经被之前读取范围完整覆盖，且不会带来新的 evidence，则确定性返回：

`NO_NEW_EVIDENCE`

必须覆盖测试：

- exact duplicate；
- 小范围被历史大范围完全包含；
- 多个历史 range 联合覆盖新的 range；
- 部分 overlap 但仍有未覆盖区间时不能错误 hard stop。

### Step 4：实现 novelty-aware `search` Hard Stop

不能只判断 query 字符串是否完全相同。

即使 query 不同，如果返回的 evidence identity / stable signature 全部已经见过，且没有新增 evidence，也应确定性返回：

`NO_NEW_EVIDENCE`

必须保证不同搜索表达不会诱导 Agent 反复消费同一批 evidence。

### Step 5：修复 256 signal signature retention

当前 bounded retention 需要改为 severity-aware。

要求：

- 总量仍严格 bounded；
- 已满 256 时，高 severity / critical 新信号可以替换更低价值信号；
- 低 severity 新信号不能仅因为“更新”就驱逐高 severity 信号；
- 同 severity 下使用确定性 tie-break，保证测试可重复；
- 不允许随着输入规模增长变成 unbounded memory。

### Step 6：50MB real workflow streaming 化

重点清除 real-agent workflow/helper 中对大文件的：

- `read_text()` whole-file load；
- `read_bytes()` whole-file load；
- 不必要的全量字符串复制；
- 可用 chunk / stream 完成却一次性加载的 hash / validation / scan。

目标不是只让 50MB 能跑，而是让同一设计能够继续到 100MB / 500MB。

### Step 7：回归顺序

代码完成后按以下顺序执行，**不能跳级**：

1. normal Core CI；
2. Evidence Intelligence Benchmark；
3. 25KB real-agent regression；
4. 5MB real-agent regression；
5. 50MB real-agent；
6. 100MB real-agent；
7. 500MB real-agent。

任何一级首次失败，都停止继续放大规模，先定位该级失败原因并修复。

## 7. 每个规模 gate 的验收标准

不能只用 workflow green 作为“成功”。每个 size gate 至少需要检查：

- root-cause key concepts 能否命中；
- 关键 evidence 能否命中；
- citation 能否命中且可恢复；
- 压缩后没有丢失决定性 evidence；
- 相比 raw baseline 有有意义的 token reduction；
- 没有异常大量重复 `get/search`；
- 内存保持 bounded；
- wall time 没有因为压缩/索引开销失控。

如果 token 降低是通过丢 evidence 换来的，则视为失败。

## 8. 关键文件

继续工作时优先检查：

```text
src/tracecite/runtime/evidence_progress.py
src/tracecite/runtime/tools.py
src/tracecite/runtime/investigation.py
benchmarks/agent-investigation/gmi_scale_host.py
.github/workflows/evidence-tracebench-50mb-real.yml
.github/workflows/evidence-tracebench-scale-build.yml
tests/
benchmarks/agent-investigation/
```

相关设计文档：

```text
docs/evidence-intelligence-experiment.zh-CN.md
```

## 9. 设计约束

继续实现时保持以下原则：

1. **Runtime 做机械事实状态，不做根因推理。**
2. **Evidence identity / coverage / novelty 判断必须确定性。**
3. **`NO_NEW_EVIDENCE` 必须基于可证明的“没有新增证据”，而不是启发式猜测。**
4. **所有 bounded 结构在输入规模继续增长时仍必须 bounded。**
5. **省 token 不能破坏 provenance、coverage disclosure 与 evidence recovery。**
6. **优先修 core/runtime 语义，再让 benchmark host 使用该语义，避免逻辑长期分叉。**
7. **大规模 benchmark 一次只提高一个规模级别。**
8. **CI / benchmark 的失败原因必须有日志或指标证据，不做无证据归因。**

## 10. 交接给下一位执行者时的最短启动路径

接手后不要重新从项目历史开始分析，直接从以下位置继续：

1. 确认分支仍为 `experiment/evidence-intelligence`，记录新的 HEAD；
2. 确认本文档之后是否已有新 commit；
3. 尝试关闭 `33150972050` 的 failed-step/log 事实缺口；
4. 检查 `EvidenceProgressTracker` 与 `tools.py` 当前是否仍未接线；
5. 从 runtime progress wiring 开始做小 commit；
6. 每完成一个独立能力就补测试；
7. 完成 Hard Stop、severity retention、streaming 后再重新开始 size gates；
8. 在 50MB 通过前不要开始 100MB / 500MB 的“成功验证”。

## 11. 当前一句话状态

**Evidence Intelligence 的主体实验和 progress state 已建立，当前真正的工作断点是：把 progress 变成 runtime 的实际执行约束，消灭重复证据读取，修复 bounded signal retention，并从已失败的 50MB real-agent gate 开始按证据逐级打通 50MB → 100MB → 500MB。**
