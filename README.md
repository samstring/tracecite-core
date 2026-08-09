<p align="center">
  <strong>TraceCite Core</strong>
</p>

<p align="center">
  <strong>Turn logs into structured evidence agents can read directly.</strong>
</p>

<p align="center">
  <a href="#"><img alt="version" src="https://img.shields.io/badge/version-0.1.0-blue"></a>
  <a href="#"><img alt="license" src="https://img.shields.io/badge/license-MIT-green"></a>
  <a href="#"><img alt="python" src="https://img.shields.io/badge/python-3.10%2B-blue"></a>
  <a href="#"><img alt="deps" src="https://img.shields.io/badge/zero%20deps-brightgreen"></a>
</p>

---

## The Problem

Three things that make log analysis harder than it should be:

**You found something, but you can't point to it.** An error is discovered, but the connection to the exact source line is lost. Another person, another session — the conclusion can't be traced back.

**Repeated lines drown the signal.** The same error appears 500 times. The output is 500 nearly identical lines. You have to count and categorize them yourself.

**You found nothing, and don't know what to try next.** You searched for `"OOM"` — no hits. What else in the log is worth searching for? Pure guesswork.

## Install

```bash
pip install -e .
```

Zero dependencies. Python 3.10+.

## Usage

```bash
# Search with keywords, limit to the last 5 minutes, collapse repeated lines
tracecite-core filter app.log --grep "Error|timeout" --last 5m --fold --json
```

That one command:

1. Extracts the last 5 minutes from `app.log`
2. Finds lines containing `Error` or `timeout`
3. Groups similar lines, showing distribution (e.g. `"status:500" × 47` instead of 47 repeated lines)
4. Outputs structured JSON

Three output files:

```bash
# Every hit: source file, line number, timestamp, what matched
result.jsonl

# Similar lines grouped, no repetition
result_tmpl.jsonl

# High-frequency words that didn't match — tells you what to search next
summary.jsonl
```

More examples:

```bash
# Everything from process 1234 between 2 PM and 3 PM
tracecite-core filter app.log --grep "." --pid 1234 --since 14:00 --until 15:00 --json

# Safe with active logs (snapshot before analyzing)
tracecite-core filter live.log --grep "CRASH" --snapshot --json

# Save parameters by tagging the run
tracecite-core filter app.log --grep "Error" --last 5m --fold --json --tag error-check
```

## vs. Dumping Raw Logs to AI

| | Raw logs to AI | TraceCite Core |
|---|---|---|
| Input | Tens of MB of raw text; AI filters on its own | You specify keywords and time window; only relevant lines extracted |
| Output format | Free text; AI parses and categorizes | Structured JSON — line numbers, timestamps, match labels are explicit |
| Repeated lines | AI decides which are duplicates | Auto-grouped with distribution counts (`×500`) |
| Nothing found? | AI re-scans full text and retries | Unmatched high-frequency words point to next search direction |
| Reproducibility | Intermediate steps differ across runs; conclusions misalign | Input frozen, parameters recorded — same input, same output |

## Architecture

<img src="architecture.svg" alt="Core execution flow: Source → Segment → Match → Filter → Fold → Events → Run" width="100%"/>

Seven steps, each producing inspectable files. Mobile extends this pipeline with device collection and behavior analysis.

## Customization

**Custom log format.** Not a standard format? Describe it:

```python
from tracecite_core import register_format, FormatSegmenter

register_format("my-app", FormatSegmenter(
    start_re=r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})",
    timestamp_formats=["%Y-%m-%d %H:%M:%S.%f"]
))
# tracecite-core filter app.log --segmenter my-app --grep "error"
```

**Save your workflow as config.** No need to remember flags:

```json
{
  "name": "crash-check",
  "source": { "type": "file", "path": "crash.log" },
  "filter": {
    "grep": "SIGABRT|SIGSEGV",
    "scope": { "last": "5m" },
    "fold": true
  }
}
```

**Chain multiple steps.** Search for crash signals, then search for stack traces within those results — progressively narrowing.

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

**Write extensions.** When you need behavior beyond built-ins, register a plugin — core code stays untouched:

```python
from tracecite_core import register_preprocessor_action
register_preprocessor_action("normalize", lambda t, **kw: t.replace("WARNING", "WARN"))
```

## See Also

- [**tracecite-mobile**](../tracecite-mobile/) — the phone version. Connect iOS/Android devices for capture and analysis.

## License

MIT
