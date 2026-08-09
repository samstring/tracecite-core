<p align="center">
  <strong>TraceCite Core</strong>
</p>

<p align="center">
  <strong>把日志变成 Agent 能直接读的结构化证据。</strong>
</p>

<p align="center">
  <a href="#"><img alt="version" src="https://img.shields.io/badge/version-0.1.0-blue"></a>
  <a href="#"><img alt="license" src="https://img.shields.io/badge/license-MIT-green"></a>
  <a href="#"><img alt="python" src="https://img.shields.io/badge/python-3.10%2B-blue"></a>
  <a href="#"><img alt="deps" src="https://img.shields.io/badge/零依赖-brightgreen"></a>
</p>

---

## 解决什么痛点

分析日志时，三个反复出现的问题：

**结论对不上行号。** 你找到一条错误，但是没法指向它在源文件的第几行。换个时间换个人来查，结论对不上。

**重复行淹没了关键信息。** 同一个错误出现 500 次，输出就是 500 行。你得自己数、自己归类。

**没找到，但不知道该换什么关键词。** 搜了 `"OOM"` 没有结果。日志里还有什么值得搜？全靠猜。

## 安装

```bash
pip install tracecite-core
```

零依赖。Python 3.10+。

## 怎么用

```bash
# 搜关键词，限定最近 5 分钟，相似行自动归类
tracecite-core filter app.log --grep "Error|timeout" --last 5m --fold --json
```

这条命令做了几件事：

1. 从 `app.log` 里提取最近 5 分钟的内容
2. 匹配包含 `Error` 或 `timeout` 的行
3. 相似的行自动归类，显示分布（比如 `"status:500" × 47` 而不是 47 行重复文本）
4. 输出结构化 JSON

跑完得到三个文件：

```bash
# 每条命中：源文件、第几行、什么时间、匹配了哪个词
result.jsonl

# 相似行已归类，不重复
result_tmpl.jsonl

# 没匹配到但频率高的词——下一步搜什么，不用猜
summary.jsonl
```

更多用法：

```bash
# 查某个进程在特定时间段的所有日志
tracecite-core filter app.log --grep "." --pid 1234 --since 14:00 --until 15:00 --json

# 安全处理正在被写入的日志（先快照再分析）
tracecite-core filter live.log --grep "CRASH" --snapshot --json

# 把常用参数写成配置文件，下次直接引用
tracecite-core filter app.log --grep "Error" --last 5m --fold --json --tag error-check
```

## 相比直接丢日志给 AI

| | 直接丢日志 | TraceCite Core |
|---|---|---|
| 输入 | 几十 MB 原始文本，AI 自己筛选 | 指定关键词和时间窗，只提取相关内容 |
| 结果格式 | 自由文本，AI 自己解析和归类 | 结构化 JSON，行号、时间、匹配词一目了然 |
| 重复行 | AI 需要自己判断哪些是重复的 | 自动归类，显示分布（`×500`） |
| 没找到怎么办 | AI 重新扫描全文再试 | 返回高频词摘要，直接提示下一步搜什么 |
| 可复现 | 两次分析中间步骤不同，结论难以对齐 | 输入被快照冻结，参数被记录，同输入同输出 |

## 整体架构

<img src="architecture.svg" alt="Core 执行流程：来源 → 分段 → 匹配 → 过滤 → 折叠 → 事件 → 运行" width="100%"/>

七步串联，每步产出可检查的文件。Mobile 在此管线之上扩展了设备采集和行为分析。

## 自定义流程

**接入自定义日志格式。** 不是标准格式？描述一下就行：

```python
from tracecite_core import register_format, FormatSegmenter

register_format("my-app", FormatSegmenter(
    start_re=r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})",  # 每行以时间戳开头
    timestamp_formats=["%Y-%m-%d %H:%M:%S.%f"]
))
# tracecite-core filter app.log --segmenter my-app --grep "error"
```

**把排查流程写成配置。** 不用每次回忆参数：

```json
{
  "name": "查崩溃",
  "source": { "type": "file", "path": "crash.log" },
  "filter": {
    "grep": "SIGABRT|SIGSEGV",
    "scope": { "last": "5m" },
    "fold": true
  }
}
```

**分步排查。** 第一步搜崩溃信号，第二步在第一步结果里搜堆栈——层层收窄。

```json
{
  "filter": {
    "stages": [
      { "grep": "SIGABRT|SIGSEGV", "tag": "signal" },
      { "grep": "backtrace|Thread \\d+", "tag": "stack" }
    ]
  }
}
```

**写扩展。** 需要内置之外的能力时，注册一个插件——不改核心代码：

```python
from tracecite_core import register_preprocessor_action
register_preprocessor_action("normalize", lambda t, **kw: t.replace("WARNING", "WARN"))
```

## 相关包

- [**tracecite-mobile**](../tracecite-mobile/) — 手机版。连 iOS/Android 设备，采集和分析一体。

## 许可证

MIT
